<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/billing.php';

function simko_image_model(): string
{
    $model = trim((string) (simko_config_or_empty()['image_model'] ?? 'grok-imagine-image-2.0'));
    return $model !== '' ? $model : 'grok-imagine-image-2.0';
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

/**
 * Documented price per picture, in xAI ticks (1 USD = 10^10 ticks), used only when the
 * response carries no usage.cost_in_usd_ticks. grok-imagine-image-2.0 is $0.04 per image
 * at the default 1K resolution: https://docs.x.ai/developers/model-capabilities/imagine (Nov 17, 2026).
 */
function simko_image_price_ticks(): int
{
    $ticks = (int) (simko_config_or_empty()['image_price_ticks'] ?? 400000000);
    return $ticks > 0 ? $ticks : 400000000;
}

function simko_ticks_usd(int $ticks): string
{
    return '$' . number_format($ticks / 10000000000, 2);
}

/**
 * Who may make pictures: the owner (not billed) and active paid subscribers (charged Grok's cost).
 * Returns role owner|subscriber|none, allowed, reason, price and today's count against the daily cap.
 */
function simko_image_access(array $user): array
{
    $userId = (int) $user['id'];
    $role = 'none';
    if (simko_is_grok_owner($user)) {
        $role = 'owner';
    } elseif (simko_subscription($userId)['status'] === 'paid') {
        $role = 'subscriber';
    } elseif (simko_can_use_grok($user)) {
        // Demo account during the preview: not billed, counted against the $1/day Grok limit.
        $role = 'demo';
    }
    $today = simko_images_today($userId);
    $cap = simko_images_daily_cap();
    $price = simko_image_price_ticks();
    $out = [
        'role' => $role,
        'allowed' => false,
        'reason' => '',
        'today' => $today,
        'cap' => $cap,
        'price_ticks' => $price,
        'price_label' => simko_ticks_usd($price),
        'billed' => $role === 'subscriber',
        'quote' => '',
    ];
    if ($role === 'none') {
        $out['reason'] = 'Pictures are for Simko SI subscribers. Subscribe to make pictures.';
        $out['quote'] = $out['reason'];
        return $out;
    }
    if ($today >= $cap) {
        $out['reason'] = 'That is today\'s ' . $cap . ' pictures. Try again tomorrow.';
        $out['quote'] = $out['reason'];
        return $out;
    }
    $out['allowed'] = true;
    $out['quote'] = $role === 'owner'
        ? 'This picture costs about ' . $out['price_label'] . ' on your Grok key. You are not billed.'
        : ($role === 'demo'
            ? 'Demo account: free during preview. A picture uses about ' . $out['price_label'] . ' of your daily Grok limit.'
            : 'This picture costs ' . $out['price_label'] . '. It is added to your bill.');
    return $out;
}

/** Ledger rows and this month's billed total for one person. */
function simko_image_ledger(int $userId): array
{
    $stmt = simko_db()->prepare(
        'SELECT image_id, model, cost_ticks, cost_source, status, created_at FROM image_charges
         WHERE user_id = ? ORDER BY id DESC LIMIT 50'
    );
    $stmt->execute([$userId]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = [
            'image_id' => (string) $row['image_id'],
            'model' => (string) $row['model'],
            'cost_ticks' => (int) $row['cost_ticks'],
            'cost_label' => simko_ticks_usd((int) $row['cost_ticks']),
            'cost_source' => (string) $row['cost_source'],
            'status' => (string) $row['status'],
            'created_at' => (int) $row['created_at'],
        ];
    }
    $monthStart = (int) strtotime(gmdate('Y-m-01 00:00:00') . ' UTC');
    $sum = simko_db()->prepare(
        "SELECT COALESCE(SUM(cost_ticks), 0), COUNT(*) FROM image_charges WHERE user_id = ? AND status = 'pending' AND created_at >= ?"
    );
    $sum->execute([$userId, $monthStart]);
    [$ticks, $count] = $sum->fetch(PDO::FETCH_NUM);
    $all = simko_db()->prepare(
        "SELECT COALESCE(SUM(cost_ticks), 0), COUNT(*) FROM image_charges WHERE user_id = ? AND status NOT IN ('owner_not_billed', 'demo_not_billed') AND created_at >= ?"
    );
    $all->execute([$userId, $monthStart]);
    [$monthTicks, $monthCount] = array_map('intval', $all->fetch(PDO::FETCH_NUM));
    return [
        'rows' => $rows,
        'billing_mode' => simko_image_billing_mode(),
        'month_pending_ticks' => (int) $ticks,
        'month_pending_label' => simko_ticks_usd((int) $ticks),
        'month_pending_count' => (int) $count,
        'month_billed_ticks' => $monthTicks,
        'month_billed_label' => simko_ticks_usd($monthTicks),
        'month_billed_count' => $monthCount,
    ];
}

function simko_image_generate(array $user, string $prompt, ?int $childId, ?string $source = null): array
{
    $userId = (int) $user['id'];
    $access = simko_image_access($user);
    if ($access['role'] === 'none') {
        simko_fail(402, $access['reason'], ['paywall' => true, 'subscribe' => true]);
    }
    if (!$access['allowed']) {
        simko_fail(429, $access['reason']);
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
    $model = simko_image_model();
    $GLOBALS['simko_spend_estimate_usd'] = simko_image_price_ticks() / 10000000000;
    // Grok image generation: POST /v1/images/generations (https://docs.x.ai/developers/model-capabilities/images/generation)
    if ($access['role'] === 'subscriber') {
        simko_grok_image_grant($userId, true);
    }
    // Editing: a picture the person uploaded goes to POST /v1/images/edits as a data URI.
    // Docs: https://docs.x.ai/developers/model-capabilities/images/editing
    $sourceUrl = null;
    if ($source !== null && $source !== '') {
        $raw = str_starts_with($source, 'data:') ? substr($source, (int) strpos($source, ',') + 1) : $source;
        $bytes = base64_decode($raw, true);
        if (!is_string($bytes) || $bytes === '' || strlen($bytes) > 8 * 1024 * 1024) {
            simko_fail(400, 'Attach a JPEG or PNG picture under 8 MB to edit.');
        }
        $mime = str_starts_with($bytes, "\xFF\xD8\xFF") ? 'image/jpeg' : (str_starts_with($bytes, "\x89PNG\r\n\x1a\n") ? 'image/png' : '');
        if ($mime === '') {
            simko_fail(415, 'Only JPEG and PNG pictures can be edited.');
        }
        $sourceUrl = 'data:' . $mime . ';base64,' . base64_encode($bytes);
    }
    try {
        $data = $sourceUrl !== null
            ? simko_curl_json(simko_xai_url('images/edits'), [
                'model' => $model,
                'prompt' => $prompt,
                'image' => ['url' => $sourceUrl, 'type' => 'image_url'],
                'response_format' => 'b64_json',
            ], 90)
            : simko_curl_json(simko_xai_url('images/generations'), [
                'model' => $model,
                'prompt' => $prompt,
                'n' => 1,
                'response_format' => 'b64_json',
            ], 60);
    } finally {
        simko_grok_image_grant(null, true);
    }
    $b64 = '';
    $first = $data['data'][0] ?? null;
    if (is_array($first)) {
        $b64 = (string) ($first['b64_json'] ?? '');
    }
    $bytes = base64_decode($b64, true);
    if (!is_string($bytes) || $bytes === '') {
        simko_fail(502, 'No picture came back.');
    }
    // Real cost from xAI (https://docs.x.ai/developers/cost-tracking), else the documented price.
    $ticks = (int) ($data['usage']['cost_in_usd_ticks'] ?? 0);
    $source = 'xai_usage';
    if ($ticks <= 0) {
        $ticks = simko_image_price_ticks();
        $source = 'price_list';
        // No usage on the reply, so the spend cap counts the price-list cost instead.
        simko_spend_add($ticks);
    }
    $dir = simko_private_dir() . '/data/images';
    if (!is_dir($dir) && !@mkdir($dir, 0750, true) && !is_dir($dir)) {
        simko_fail(500, 'Simko SI cannot store the picture.');
    }
    $id = bin2hex(random_bytes(8));
    file_put_contents($dir . '/' . $id . '.png', $bytes);
    $now = time();
    $status = $access['role'] === 'owner' ? 'owner_not_billed' : ($access['role'] === 'demo' ? 'demo_not_billed' : 'pending');
    $db = simko_db();
    $db->beginTransaction();
    $stmt = $db->prepare(
        'INSERT INTO generated_images (id, user_id, child_profile_id, prompt, created_at) VALUES (?, ?, ?, ?, ?)'
    );
    $stmt->execute([$id, $userId, $childId, simko_clip($prompt, 240), $now]);
    $charge = $db->prepare(
        'INSERT INTO image_charges (user_id, image_id, model, cost_ticks, cost_source, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)'
    );
    $charge->execute([$userId, $id, $model, $ticks, $source, $status, $now]);
    $chargeId = (int) $db->lastInsertId();
    $db->commit();
    $billing = null;
    if ($status === 'pending') {
        $billing = simko_image_billing_after_charge($chargeId);
        $status = (string) (simko_db()->query('SELECT status FROM image_charges WHERE id = ' . $chargeId)->fetchColumn() ?: $status);
    }
    return [
        'id' => $id,
        'prompt' => simko_clip($prompt, 240),
        'created_at' => $now,
        'cost_ticks' => $ticks,
        'cost_label' => simko_ticks_usd($ticks),
        'cost_source' => $source,
        'charge_status' => $status,
        'billing' => $billing,
        'model' => $model,
    ];
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
