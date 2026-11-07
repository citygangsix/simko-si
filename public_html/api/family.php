<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

$body = simko_require_post_json();
$user = simko_require_user();
$op = (string) ($body['op'] ?? '');
$parentId = (int) $user['id'];

switch ($op) {
    case 'status':
        simko_family_status($user);
        break;
    case 'consent':
        simko_family_consent($user, $body);
        break;
    case 'create-child':
        simko_family_create_child($user, $body);
        break;
    case 'delete-child':
        simko_family_delete_child($parentId, $body);
        break;
    case 'delete-chat':
        simko_family_delete_chat($parentId, $body);
        break;
    default:
        simko_fail(400, 'That family step is not recognized.');
}

function simko_family_characters(): array
{
    return [
        'turtle' => 'Turtle',
        'dolphin' => 'Dolphin',
        'octopus' => 'Octopus',
        'whale' => 'Whale',
        'seahorse' => 'Seahorse',
        'coral' => 'Coral',
        'manta' => 'Manta',
        'otter' => 'Otter',
    ];
}

function simko_family_age_bands(): array
{
    return ['Ages 3 to 6', 'Ages 7 to 9', 'Ages 10 to 12', 'Ages 13 to 15'];
}

function simko_family_parent_ready(array $user): void
{
    if ((int) ($user['confirmed'] ?? 0) !== 1) {
        simko_fail(403, 'Confirm your email before adding a child.');
    }
    if ((int) ($user['parent_consent_at'] ?? 0) < 1) {
        simko_fail(403, 'A parent has to agree before a child profile can be added.');
    }
}

function simko_family_status(array $user): void
{
    $parentId = (int) $user['id'];
    simko_ok([
        'email' => $user['email'],
        'confirmed' => (int) $user['confirmed'] === 1,
        'parent' => (int) ($user['parent_consent_at'] ?? 0) > 0,
        'consent_at' => (int) ($user['parent_consent_at'] ?? 0),
        'children' => simko_family_children($parentId, true),
        'characters' => simko_family_characters(),
        'age_bands' => simko_family_age_bands(),
    ]);
}

function simko_family_consent(array $user, array $body): void
{
    if (empty($body['consent'])) {
        simko_fail(400, 'A parent has to agree before a child profile can be added.');
    }
    if ((int) ($user['parent_consent_at'] ?? 0) > 0) {
        simko_ok(['consent_at' => (int) $user['parent_consent_at']]);
    }
    $now = time();
    $stmt = simko_db()->prepare('UPDATE users SET role = ?, parent_consent_at = ? WHERE id = ?');
    $stmt->execute(['parent', $now, (int) $user['id']]);
    simko_ok(['consent_at' => $now]);
}

function simko_family_create_child(array $user, array $body): void
{
    simko_family_reject_child_pii($body);
    simko_family_parent_ready($user);
    $name = trim((string) preg_replace('/\s+/', ' ', (string) ($body['display_name'] ?? '')));
    if ($name === '' || simko_len($name) > 24 || str_contains($name, '@')) {
        simko_fail(400, 'Use a short display name, with no email address.');
    }
    $avatar = strtolower(trim((string) ($body['avatar'] ?? '')));
    $characters = simko_family_characters();
    if (!isset($characters[$avatar])) {
        simko_fail(400, 'Pick a character for this child.');
    }
    $band = trim((string) ($body['age_band'] ?? ''));
    if (!in_array($band, simko_family_age_bands(), true)) {
        simko_fail(400, 'Pick an age band. A birthdate is not stored.');
    }
    $db = simko_db();
    $count = $db->prepare('SELECT COUNT(*) FROM child_profiles WHERE parent_user_id = ?');
    $count->execute([(int) $user['id']]);
    if ((int) $count->fetchColumn() >= 12) {
        simko_fail(400, 'This account already has 12 child profiles.');
    }
    $now = time();
    $insert = $db->prepare(
        'INSERT INTO child_profiles (parent_user_id, display_name, avatar, age_band, created_at)
         VALUES (?, ?, ?, ?, ?)'
    );
    $insert->execute([(int) $user['id'], $name, $avatar, $band, $now]);
    simko_ok(['child' => [
        'id' => (int) $db->lastInsertId(),
        'display_name' => $name,
        'avatar' => $avatar,
        'character' => $characters[$avatar],
        'age_band' => $band,
        'created_at' => $now,
        'chats' => [],
    ]]);
}

function simko_family_reject_child_pii(array $body): void
{
    $banned = ['email', 'birthdate', 'birthday', 'dob', 'last_name', 'lastname', 'surname', 'full_name'];
    foreach ($banned as $key) {
        if (isset($body[$key]) && trim((string) $body[$key]) !== '') {
            simko_fail(400, 'A child profile only stores a display name, a character, and an age band.');
        }
    }
}

function simko_family_children(int $parentId, bool $withChats): array
{
    $stmt = simko_db()->prepare(
        'SELECT id, display_name, avatar, age_band, created_at
         FROM child_profiles WHERE parent_user_id = ? ORDER BY id ASC'
    );
    $stmt->execute([$parentId]);
    $characters = simko_family_characters();
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $child = [
            'id' => (int) $row['id'],
            'display_name' => $row['display_name'],
            'avatar' => $row['avatar'],
            'character' => $characters[$row['avatar']] ?? $row['avatar'],
            'age_band' => $row['age_band'],
            'created_at' => (int) $row['created_at'],
        ];
        if ($withChats) {
            $child['chats'] = simko_family_chat_rows($parentId, (int) $row['id']);
        }
        $rows[] = $child;
    }
    return $rows;
}

function simko_family_chat_rows(int $parentId, int $childId): array
{
    $stmt = simko_db()->prepare(
        'SELECT id, title, updated_at FROM chats
         WHERE user_id = ? AND child_profile_id = ?
         ORDER BY updated_at DESC'
    );
    $stmt->execute([$parentId, $childId]);
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

function simko_family_delete_child(int $parentId, array $body): void
{
    $childId = (int) ($body['child_id'] ?? 0);
    $child = simko_child_owned($parentId, $childId);
    if (!$child) {
        simko_fail(404, 'That child profile is not on this account.');
    }
    $db = simko_db();
    $db->beginTransaction();
    try {
        $chats = $db->prepare('SELECT id FROM chats WHERE user_id = ? AND child_profile_id = ?');
        $chats->execute([$parentId, $childId]);
        $ids = $chats->fetchAll();
        $wipe = $db->prepare('DELETE FROM messages WHERE chat_id = ?');
        foreach ($ids as $chat) {
            $wipe->execute([$chat['id']]);
        }
        $dropChats = $db->prepare('DELETE FROM chats WHERE user_id = ? AND child_profile_id = ?');
        $dropChats->execute([$parentId, $childId]);
        $drop = $db->prepare('DELETE FROM child_profiles WHERE id = ? AND parent_user_id = ?');
        $drop->execute([$childId, $parentId]);
        $db->commit();
    } catch (Throwable $e) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        throw $e;
    }
    simko_ok();
}

function simko_family_delete_chat(int $parentId, array $body): void
{
    require_once __DIR__ . '/approvals.php';
    $chatId = (string) ($body['session_id'] ?? '');
    simko_guard_approval($parentId, $body, 'delete', 'Delete a child chat', [
        'op' => 'delete-chat',
        'session_id' => $chatId,
    ]);
    $chat = simko_chat_owned($parentId, $chatId);
    if (!$chat || (int) ($chat['child_profile_id'] ?? 0) < 1) {
        simko_fail(404, 'That chat is not on this account.');
    }
    if (!simko_child_owned($parentId, (int) $chat['child_profile_id'])) {
        simko_fail(404, 'That chat is not on this account.');
    }
    $db = simko_db();
    $db->prepare('DELETE FROM messages WHERE chat_id = ?')->execute([$chatId]);
    $db->prepare('DELETE FROM chats WHERE id = ? AND user_id = ?')->execute([$chatId, $parentId]);
    simko_ok();
}
