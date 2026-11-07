<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_share_create(int $userId): array
{
    $labels = [
        'career' => 'Career', 'health' => 'Health', 'family' => 'Family', 'money' => 'Money',
        'friends' => 'Friends', 'home' => 'Home', 'learning' => 'Learning', 'love' => 'Love',
    ];
    $lines = ['Lifebook progress'];
    $stmt = simko_db()->prepare('SELECT category, tone FROM life_events WHERE user_id = ? ORDER BY id ASC');
    $stmt->execute([$userId]);
    $seen = [];
    foreach ($stmt->fetchAll() as $row) {
        $seen[(string) $row['category']] = (string) $row['tone'];
    }
    if ($seen === []) {
        $lines[] = 'No Lifebook tags yet.';
    }
    foreach ($seen as $id => $tone) {
        $lines[] = ($labels[$id] ?? $id) . ': ' . $tone;
    }
    $token = bin2hex(random_bytes(24));
    $stmt = simko_db()->prepare(
        'INSERT INTO shares (token, user_id, kind, body, revoked, created_at) VALUES (?, ?, ?, ?, 0, ?)'
    );
    $stmt->execute([$token, $userId, 'lifebook', implode("\n", $lines), time()]);
    $site = rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/');
    return ['token' => $token, 'url' => $site . '/api/share?token=' . $token];
}

function simko_share_revoke(int $userId, string $token): void
{
    $stmt = simko_db()->prepare('UPDATE shares SET revoked = 1 WHERE token = ? AND user_id = ? AND revoked = 0');
    $stmt->execute([$token, $userId]);
    if ($stmt->rowCount() < 1) {
        simko_fail(404, 'That share link is not on this account.');
    }
}

function simko_share_public(string $token): ?array
{
    if (!preg_match('/^[a-f0-9]{48}$/', $token)) {
        return null;
    }
    $stmt = simko_db()->prepare('SELECT body, created_at, revoked FROM shares WHERE token = ?');
    $stmt->execute([$token]);
    $row = $stmt->fetch();
    if (!$row || (int) $row['revoked'] === 1) {
        return null;
    }
    return ['body' => (string) $row['body'], 'created_at' => (int) $row['created_at']];
}
