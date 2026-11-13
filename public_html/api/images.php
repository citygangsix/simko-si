<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';

function simko_image_model(): string
{
    $model = trim((string) (simko_config_or_empty()['image_model'] ?? 'grok-2-image'));
    return $model !== '' ? $model : 'grok-2-image';
}

function simko_image_blocked(string $prompt, bool $kid): bool
{
    $words = ['nude', 'naked', 'porn', 'xxx', 'nsfw', 'sex'];
    if ($kid) {
        $words = array_merge($words, ['weapon', 'gun', 'gore', 'drug', 'kill']);
    }
    $hay = strtolower($prompt);
    if (preg_match('/\b(video|movie|animate this|make a clip)\b/i', $prompt)) {
        return true;
    }
    foreach ($words as $word) {
        if (str_contains($hay, $word)) {
            return true;
        }
    }
    return false;
}

function simko_image_generate(int $userId, string $prompt, ?int $childId): array
{
    if (!simko_images_allowed($userId)) {
        simko_fail(402, 'Pictures are on the $9.99/month plan.', ['paywall' => true]);
    }
    $prompt = trim($prompt);
    if ($prompt === '' || simko_len($prompt) > 500) {
        simko_fail(400, 'Describe the picture in a short prompt.');
    }
    $kid = $childId !== null;
    if (simko_image_blocked($prompt, $kid)) {
        simko_fail(400, preg_match('/\b(video|movie|clip)\b/i', $prompt)
            ? 'Video is not made here. Video stays on a rented GPU, on the desktop app Wan path.'
            : 'That picture is blocked.');
    }
    $data = simko_curl_json(simko_xai_url('images/generations'), [
        'model' => simko_image_model(),
        'prompt' => $prompt,
        'n' => 1,
        'response_format' => 'b64_json',
    ], 60);
    $b64 = '';
    $first = $data['data'][0] ?? null;
    if (is_array($first)) {
        $b64 = (string) ($first['b64_json'] ?? '');
    }
    $bytes = base64_decode($b64, true);
    if (!is_string($bytes) || $bytes === '') {
        simko_fail(502, 'No picture came back.');
    }
    $dir = simko_private_dir() . '/data/images';
    if (!is_dir($dir) && !@mkdir($dir, 0750, true) && !is_dir($dir)) {
        simko_fail(500, 'Simko SI cannot store the picture.');
    }
    $id = bin2hex(random_bytes(8));
    file_put_contents($dir . '/' . $id . '.png', $bytes);
    $now = time();
    $stmt = simko_db()->prepare(
        'INSERT INTO generated_images (id, user_id, child_profile_id, prompt, created_at) VALUES (?, ?, ?, ?, ?)'
    );
    $stmt->execute([$id, $userId, $childId, simko_clip($prompt, 240), $now]);
    return ['id' => $id, 'prompt' => simko_clip($prompt, 240), 'created_at' => $now];
}

function simko_image_rows(int $userId): array
{
    $stmt = simko_db()->prepare(
        'SELECT id, prompt, created_at FROM generated_images WHERE user_id = ? ORDER BY created_at DESC LIMIT 24'
    );
    $stmt->execute([$userId]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = [
            'id' => $row['id'],
            'prompt' => $row['prompt'],
            'created_at' => (int) $row['created_at'],
            'url' => '/api/image?id=' . rawurlencode((string) $row['id']),
        ];
    }
    return $rows;
}
