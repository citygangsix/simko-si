<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

$body = simko_require_post_json();
$user = simko_require_user();
$op = (string) ($body['op'] ?? '');
$userId = (int) $user['id'];

$childId = simko_requested_child($userId, $body);

switch ($op) {
    case 'list':
        simko_ok(['sessions' => simko_list_chats($userId, $childId)]);
        break;
    case 'create':
        simko_ok(['session' => simko_create_chat($userId, (string) ($body['title'] ?? ''), $childId)]);
        break;
    case 'get':
        $chat = simko_chat_owned($userId, (string) ($body['session_id'] ?? ''));
        if (!$chat || !simko_chat_matches_child($chat, $childId)) {
            simko_fail(404, 'That chat is not on this account.');
        }
        simko_ok(['session' => simko_public_session($chat, true)]);
        break;
    case 'append':
        simko_append_message($userId, $body, $childId);
        simko_ok();
        break;
    case 'search':
        simko_ok(['sessions' => simko_search_chats($userId, (string) ($body['q'] ?? ''))]);
        break;
    case 'relay':
        simko_relay($userId, $body);
        simko_ok();
        break;
    default:
        simko_fail(400, 'That chat action is not recognized.');
}

function simko_chat_matches_child(array $chat, ?int $childId): bool
{
    if ($childId === null) {
        return true;
    }
    return (int) ($chat['child_profile_id'] ?? 0) === $childId;
}

function simko_list_chats(int $userId, ?int $childId = null): array
{
    if ($childId === null) {
        $stmt = simko_db()->prepare(
            'SELECT id, title, updated_at FROM chats
             WHERE user_id = ? AND child_profile_id IS NULL
             ORDER BY updated_at DESC'
        );
        $stmt->execute([$userId]);
    } else {
        $stmt = simko_db()->prepare(
            'SELECT id, title, updated_at FROM chats
             WHERE user_id = ? AND child_profile_id = ?
             ORDER BY updated_at DESC'
        );
        $stmt->execute([$userId, $childId]);
    }
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = [
            'id' => $row['id'],
            'title' => $row['title'],
            'updated_at' => (int) $row['updated_at'],
        ];
    }
    return $rows;
}

function simko_create_chat(int $userId, string $title, ?int $childId = null): array
{
    $title = trim($title);
    if ($title === '') {
        $title = 'Chat';
    }
    $title = simko_clip($title, 80);
    $id = 'c' . bin2hex(random_bytes(8));
    $now = time();
    $stmt = simko_db()->prepare(
        'INSERT INTO chats (id, user_id, title, created_at, updated_at, child_profile_id) VALUES (?, ?, ?, ?, ?, ?)'
    );
    $stmt->execute([$id, $userId, $title, $now, $now, $childId]);
    return [
        'id' => $id,
        'title' => $title,
        'updated_at' => $now,
        'messages' => [],
    ];
}

function simko_append_message(int $userId, array $body, ?int $childId = null): void
{
    $chat = simko_chat_owned($userId, (string) ($body['session_id'] ?? ''));
    if (!$chat || !simko_chat_matches_child($chat, $childId)) {
        simko_fail(404, 'That chat is not on this account.');
    }
    $role = (string) ($body['role'] ?? '');
    if (!in_array($role, ['user', 'assistant', 'relay', 'relay_out'], true)) {
        simko_fail(400, 'That message could not be saved.');
    }
    $text = trim((string) ($body['text'] ?? ''));
    if ($text === '') {
        simko_fail(400, 'Type a message, then Send.');
    }
    if (simko_len($text) > simko_max_chars()) {
        simko_fail(413, 'That message is too long. Keep it under ' . simko_max_chars() . ' characters.');
    }
    $db = simko_db();
    if ($role === 'user' && preg_match('/^Chat \d+$/', (string) $chat['title'])) {
        $count = $db->prepare("SELECT COUNT(*) FROM messages WHERE chat_id = ? AND role = 'user'");
        $count->execute([$chat['id']]);
        if ((int) $count->fetchColumn() === 0) {
            $title = simko_clip(preg_replace('/\s+/', ' ', $text) ?? $text, 42);
            $rename = $db->prepare('UPDATE chats SET title = ? WHERE id = ?');
            $rename->execute([$title, $chat['id']]);
        }
    }
    $insert = $db->prepare(
        'INSERT INTO messages (chat_id, role, body, from_title, to_title, created_at)
         VALUES (?, ?, ?, ?, ?, ?)'
    );
    $insert->execute([
        $chat['id'],
        $role,
        $text,
        isset($body['from_title']) ? simko_clip((string) $body['from_title'], 80) : null,
        isset($body['to_title']) ? simko_clip((string) $body['to_title'], 80) : null,
        time(),
    ]);
    $touch = $db->prepare('UPDATE chats SET updated_at = ? WHERE id = ?');
    $touch->execute([time(), $chat['id']]);
}

function simko_search_chats(int $userId, string $query): array
{
    $query = trim($query);
    if ($query === '') {
        return simko_list_chats($userId, null);
    }
    $like = '%' . str_replace(['!', '%', '_'], ['!!', '!%', '!_'], $query) . '%';
    $stmt = simko_db()->prepare(
        "SELECT DISTINCT c.id, c.title, c.updated_at
         FROM chats c
         LEFT JOIN messages m ON m.chat_id = c.id
         WHERE c.user_id = ? AND c.child_profile_id IS NULL
           AND (c.title LIKE ? ESCAPE '!' OR m.body LIKE ? ESCAPE '!')
         ORDER BY c.updated_at DESC"
    );
    $stmt->execute([$userId, $like, $like]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = [
            'id' => $row['id'],
            'title' => $row['title'],
            'updated_at' => (int) $row['updated_at'],
        ];
    }
    return $rows;
}

function simko_relay(int $userId, array $body): void
{
    $text = trim((string) ($body['text'] ?? ''));
    if ($text === '') {
        simko_fail(400, 'Type a message, then Send to chat.');
    }
    if (simko_len($text) > simko_max_chars()) {
        simko_fail(413, 'That message is too long. Keep it under ' . simko_max_chars() . ' characters.');
    }
    $from = simko_chat_owned($userId, (string) ($body['from_session_id'] ?? ''));
    $to = simko_chat_owned($userId, (string) ($body['to_session_id'] ?? ''));
    if (!$from || !$to || $from['id'] === $to['id']) {
        simko_fail(400, 'Open another chat first.');
    }
    $db = simko_db();
    $db->beginTransaction();
    try {
        $insert = $db->prepare(
            'INSERT INTO messages (chat_id, role, body, from_title, to_title, created_at)
             VALUES (?, ?, ?, ?, ?, ?)'
        );
        $now = time();
        $insert->execute([$from['id'], 'relay_out', $text, null, $to['title'], $now]);
        $insert->execute([$to['id'], 'relay', $text, $from['title'], null, $now]);
        $touch = $db->prepare('UPDATE chats SET updated_at = ? WHERE id = ?');
        $touch->execute([$now, $from['id']]);
        $touch->execute([$now, $to['id']]);
        $db->commit();
    } catch (Throwable $e) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        throw $e;
    }
}
