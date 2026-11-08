<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_memory_rows(int $userId, ?int $childId): array
{
    if ($childId === null) {
        $stmt = simko_db()->prepare(
            'SELECT id, fact, created_at FROM memories
             WHERE user_id = ? AND child_profile_id IS NULL ORDER BY id DESC'
        );
        $stmt->execute([$userId]);
    } else {
        $stmt = simko_db()->prepare(
            'SELECT id, fact, created_at FROM memories
             WHERE user_id = ? AND child_profile_id = ? ORDER BY id DESC'
        );
        $stmt->execute([$userId, $childId]);
    }
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = ['id' => (int) $row['id'], 'fact' => $row['fact'], 'created_at' => (int) $row['created_at']];
    }
    return $rows;
}

function simko_memory_prompt(int $userId, ?int $childId): string
{
    if (!simko_flag('memory')) {
        return '';
    }
    $rows = simko_memory_rows($userId, $childId);
    if ($rows === []) {
        return '';
    }
    $lines = array_map(static fn (array $row): string => '- ' . $row['fact'], array_reverse($rows));
    return "Facts this person asked you to remember:\n" . implode("\n", $lines);
}

function simko_memory_learn(int $userId, ?int $childId, string $text): void
{
    if (!simko_flag('memory')) {
        return;
    }
    $patterns = [
        '/\bmy name is\s+([^.!\n]{1,40})/i',
        '/\bi like\s+([^.!\n]{1,60})/i',
        '/\bi am\s+([^.!\n]{1,60})/i',
        '/\bremember that\s+([^.!\n]{1,120})/i',
    ];
    foreach ($patterns as $pattern) {
        if (!preg_match($pattern, $text, $match)) {
            continue;
        }
        $fact = trim((string) preg_replace('/\s+/', ' ', $match[0]));
        if ($fact === '') {
            continue;
        }
        $exists = simko_db()->prepare(
            'SELECT id FROM memories WHERE user_id = ? AND fact = ? AND '
            . ($childId === null ? 'child_profile_id IS NULL' : 'child_profile_id = ?')
        );
        $params = [$userId, $fact];
        if ($childId !== null) {
            $params[] = $childId;
        }
        $exists->execute($params);
        if ($exists->fetch()) {
            continue;
        }
        $insert = simko_db()->prepare(
            'INSERT INTO memories (user_id, child_profile_id, fact, created_at) VALUES (?, ?, ?, ?)'
        );
        $insert->execute([$userId, $childId, $fact, time()]);
    }
}

function simko_memory_delete(int $userId, int $memoryId): void
{
    $stmt = simko_db()->prepare('DELETE FROM memories WHERE id = ? AND user_id = ?');
    $stmt->execute([$memoryId, $userId]);
    if ($stmt->rowCount() < 1) {
        simko_fail(404, 'That memory is not on this account.');
    }
}
