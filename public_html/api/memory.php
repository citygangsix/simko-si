<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

$body = simko_require_post_json();
$op = (string) ($body['op'] ?? 'list');
$user = simko_current_user();

if ($op === 'list') {
    simko_ok(simko_life_payload($user ? (int) $user['id'] : 0));
}
if (!$user) {
    simko_fail(401, 'Sign in to tag a line.');
}
$userId = (int) $user['id'];

if ($op === 'tag') {
    $found = simko_classify((string) ($body['text'] ?? ''));
    $tagged = false;
    if ($found) {
        $stmt = simko_db()->prepare(
            'INSERT INTO life_events (user_id, category, label, tone, created_at) VALUES (?, ?, ?, ?, ?)'
        );
        $stmt->execute([$userId, $found['id'], $found['label'], $found['tone'], time()]);
        $tagged = true;
    }
    $payload = simko_life_payload($userId);
    $payload['tagged'] = $tagged;
    simko_ok($payload);
}

if ($op === 'retag') {
    $category = (string) ($body['category'] ?? '');
    $labels = simko_life_categories();
    if (!isset($labels[$category])) {
        simko_fail(400, 'That area is not in the lifebook.');
    }
    $db = simko_db();
    $latest = $db->prepare('SELECT id FROM life_events WHERE user_id = ? ORDER BY id DESC LIMIT 1');
    $latest->execute([$userId]);
    $row = $latest->fetch();
    if (!$row) {
        simko_fail(400, 'Nothing to tag.');
    }
    $update = $db->prepare('UPDATE life_events SET category = ?, label = ? WHERE id = ?');
    $update->execute([$category, $labels[$category], (int) $row['id']]);
    $payload = simko_life_payload($userId);
    simko_ok($payload);
}

simko_fail(400, 'That lifebook step is not recognized.');

function simko_life_categories(): array
{
    return [
        'career' => 'Career',
        'health' => 'Health and Fitness',
        'family' => 'Parenting',
        'money' => 'Financial Life',
        'friends' => 'Social Life',
        'home' => 'Quality of Life',
        'vision' => 'Life Vision',
        'learn' => 'Intellectual Life',
        'love' => 'Love Relationship',
    ];
}

function simko_classify(string $text): ?array
{
    $hay = strtolower($text);
    $rules = [
        'career' => '/\b(career|job|work|office)\b/',
        'health' => '/\b(health|gym|sleep|slept|fitness)\b/',
        'family' => '/\b(family|kids|kid|parent)\b/',
        'money' => '/\b(money|budget|bill|paid|afford)\b/',
        'friends' => '/\b(friend|friends)\b/',
        'home' => '/\b(home|evening|house|restless)\b/',
        'vision' => '/\b(goal|vision|dream)\b/',
        'learn' => '/\b(learn|learning|read|book|study)\b/',
        'love' => '/\b(love|partner|date|romance)\b/',
    ];
    $labels = simko_life_categories();
    foreach ($rules as $id => $pattern) {
        if (!preg_match($pattern, $hay)) {
            continue;
        }
        $tone = 'in play';
        if (preg_match('/\b(badly|tight|strained|skipped|restless|worried|anxious)\b/', $hay)) {
            $tone = 'strained';
        } elseif (preg_match('/\b(well|great|good|calm|glad)\b/', $hay)) {
            $tone = 'doing well';
        }
        return ['id' => $id, 'label' => $labels[$id], 'tone' => $tone];
    }
    return null;
}

function simko_life_payload(int $userId): array
{
    $labels = simko_life_categories();
    $statuses = [];
    foreach ($labels as $id => $label) {
        $statuses[$id] = 'not discussed';
    }
    $tags = [];
    $counts = [];
    foreach ($labels as $id => $label) {
        $counts[$id] = 0;
    }
    $dominance = '';
    $best = 0;
    if ($userId > 0) {
        $stmt = simko_db()->prepare(
            'SELECT category, label, tone FROM life_events WHERE user_id = ? ORDER BY id ASC'
        );
        $stmt->execute([$userId]);
        foreach ($stmt->fetchAll() as $row) {
            $id = (string) $row['category'];
            if (!isset($labels[$id])) {
                continue;
            }
            $counts[$id]++;
            $statuses[$id] = (string) $row['tone'];
            $tags[] = ['category' => $id, 'label' => $labels[$id]];
            if ($counts[$id] > $best) {
                $best = $counts[$id];
                $dominance = $labels[$id];
            }
        }
    }
    $countRows = [];
    foreach ($labels as $id => $label) {
        $countRows[] = ['id' => $id, 'label' => $label, 'n' => $counts[$id]];
    }
    $categories = [];
    foreach ($labels as $id => $label) {
        $categories[] = ['id' => $id, 'label' => $label];
    }
    return [
        'categories' => $categories,
        'statuses' => $statuses,
        'tags' => $tags,
        'counts' => $countRows,
        'dominance_note' => $dominance === '' ? 'Words only. No grade.' : $dominance . ' is the thread in front.',
    ];
}
