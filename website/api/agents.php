<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/voice-assignments.php';

function simko_agent_create(int $userId, string $name, string $persona): array
{
    $name = trim($name);
    $persona = trim($persona);
    if ($name === '' || $persona === '') {
        simko_fail(400, 'An agent needs a name and a short persona.');
    }
    $db = simko_db();
    return simko_voice_atomic($db, function () use ($db,$userId,$name,$persona): array {
        $count = $db->prepare('SELECT COUNT(*) FROM agents WHERE user_id = ?');
        $count->execute([$userId]);
        if ((int)$count->fetchColumn() >= 4) simko_fail(400, 'Four agents is the most that can sit side by side.');
        $voice=simko_voice_next($db,$userId);
        $chatId='c'.bin2hex(random_bytes(8)); $now=time();
        $db->prepare('INSERT INTO chats (id,user_id,title,created_at,updated_at,child_profile_id,voice_id) VALUES (?,?,?,?,?,NULL,?)')->execute([$chatId,$userId,simko_clip($name,80),$now,$now,$voice]);
        $db->prepare('INSERT INTO agents (user_id,name,persona,chat_id,created_at,voice_id) VALUES (?,?,?,?,?,?)')->execute([$userId,simko_clip($name,40),simko_clip($persona,240),$chatId,$now,$voice]);
        return ['id'=>(int)$db->lastInsertId(),'name'=>simko_clip($name,40),'persona'=>simko_clip($persona,240),'chat_id'=>$chatId,'voice_id'=>$voice];
    });
}

function simko_agent_rows(int $userId): array
{
    $stmt = simko_db()->prepare('SELECT id, name, persona, chat_id, voice_id FROM agents WHERE user_id = ? ORDER BY id ASC');
    $stmt->execute([$userId]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = [
            'id' => (int) $row['id'],
            'name' => $row['name'],
            'persona' => $row['persona'],
            'chat_id' => $row['chat_id'],
            'voice_id' => $row['voice_id'],
        ];
    }
    return $rows;
}

function simko_agent_owned(int $userId, int $agentId): ?array
{
    $stmt = simko_db()->prepare('SELECT id, name, persona, chat_id, voice_id FROM agents WHERE id = ? AND user_id = ?');
    $stmt->execute([$agentId, $userId]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function simko_agent_hand(int $userId, int $fromId, int $toId, string $text): void
{
    $text = trim($text);
    if ($text === '' || $fromId === $toId) {
        simko_fail(400, 'Pick two agents and a message to hand over.');
    }
    $from = simko_agent_owned($userId, $fromId);
    $to = simko_agent_owned($userId, $toId);
    if (!$from || !$to) {
        simko_fail(404, 'Those agents are not on this account.');
    }
    $now = time();
    $db = simko_db();
    $insert = $db->prepare(
        'INSERT INTO messages (chat_id, role, body, from_title, to_title, created_at) VALUES (?, ?, ?, ?, ?, ?)'
    );
    $insert->execute([$from['chat_id'], 'relay_out', $text, null, $to['name'], $now]);
    $insert->execute([$to['chat_id'], 'relay', $text, $from['name'], null, $now]);
    $touch = $db->prepare('UPDATE chats SET updated_at = ? WHERE id = ?');
    $touch->execute([$now, $from['chat_id']]);
    $touch->execute([$now, $to['chat_id']]);
}
