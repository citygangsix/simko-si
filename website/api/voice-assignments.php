<?php
declare(strict_types=1);
require_once __DIR__ . '/voice-catalog.php';

function simko_voice_atomic(PDO $db, callable $run): mixed
{
    $db->exec('BEGIN IMMEDIATE');
    try { $result = $run(); $db->exec('COMMIT'); return $result; }
    catch (Throwable $e) { $db->exec('ROLLBACK'); throw $e; }
}

function simko_voice_next(PDO $db, int $userId): string
{
    $counts = array_fill_keys(array_column(simko_voice_catalog(), 'id'), 0);
    // A linked agent/chat is ONE chatbot, never counted twice.
    $q = $db->prepare('SELECT voice_id FROM chats WHERE user_id = ? UNION ALL SELECT a.voice_id FROM agents a WHERE a.user_id = ? AND NOT EXISTS (SELECT 1 FROM chats c WHERE c.id = a.chat_id AND c.user_id = a.user_id)');
    $q->execute([$userId, $userId]);
    foreach ($q->fetchAll(PDO::FETCH_COLUMN) as $id) if (isset($counts[$id])) $counts[$id]++;
    $least = min($counts);
    foreach ($counts as $id => $count) if ($count === $least) return $id;
    return 'coral';
}

function simko_voice_migrate(PDO $db): array
{
    return simko_voice_atomic($db, function () use ($db): array {
        $added = []; $filled = 0;
        foreach (['chats', 'agents'] as $table) {
            $columns = $db->query('PRAGMA table_info(' . $table . ')')->fetchAll(PDO::FETCH_ASSOC);
            if (!in_array('voice_id', array_column($columns, 'name'), true)) {
                $db->exec('ALTER TABLE ' . $table . ' ADD COLUMN voice_id TEXT NULL'); $added[] = $table;
            }
        }
        foreach ($db->query('SELECT id,user_id,chat_id,voice_id FROM agents ORDER BY user_id,id')->fetchAll(PDO::FETCH_ASSOC) as $agent) {
            $q=$db->prepare('SELECT voice_id FROM chats WHERE id=? AND user_id=?'); $q->execute([$agent['chat_id'],$agent['user_id']]);
            $chatVoice=$q->fetchColumn();
            $voice=simko_voice_by_id((string)$agent['voice_id']) ? $agent['voice_id'] : (simko_voice_by_id((string)$chatVoice) ? $chatVoice : simko_voice_next($db,(int)$agent['user_id']));
            if ($agent['voice_id'] !== $voice) { $db->prepare('UPDATE agents SET voice_id=? WHERE id=?')->execute([$voice,$agent['id']]); $filled++; }
            $db->prepare('UPDATE chats SET voice_id=? WHERE id=? AND user_id=?')->execute([$voice,$agent['chat_id'],$agent['user_id']]);
        }
        foreach ($db->query('SELECT id,user_id,voice_id FROM chats ORDER BY user_id,created_at,id')->fetchAll(PDO::FETCH_ASSOC) as $chat) {
            if (simko_voice_by_id((string)$chat['voice_id'])) continue;
            $voice=simko_voice_next($db,(int)$chat['user_id']);
            $db->prepare('UPDATE chats SET voice_id=? WHERE id=?')->execute([$voice,$chat['id']]); $filled++;
        }
        return ['added_columns'=>$added,'backfilled'=>$filled];
    });
}

function simko_voice_override(PDO $db, int $userId, string $chatId, string $voice, ?int $childId=null): bool
{
    if (!simko_voice_by_id($voice)) throw new InvalidArgumentException('Unknown voice');
    return simko_voice_atomic($db, function () use ($db,$userId,$chatId,$voice,$childId): bool {
        $q=$db->prepare('SELECT child_profile_id FROM chats WHERE id=? AND user_id=?'); $q->execute([$chatId,$userId]); $row=$q->fetch(PDO::FETCH_ASSOC);
        if (!$row || ($childId !== null && (int)$row['child_profile_id'] !== $childId)) return false;
        $db->prepare('UPDATE chats SET voice_id=? WHERE id=? AND user_id=?')->execute([$voice,$chatId,$userId]);
        $db->prepare('UPDATE agents SET voice_id=? WHERE chat_id=? AND user_id=?')->execute([$voice,$chatId,$userId]);
        return true;
    });
}
