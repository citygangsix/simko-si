<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';


function simko_plan_amount(): int
{
    return 999;
}

function simko_plan_label(): string
{
    return '$9.99/month';
}

function simko_plan_name(): string
{
    return 'Simko SI $9.99/month';
}

function simko_billing_provider(): string
{
    $cfg = simko_config_or_empty();
    $env = getenv('BILLING_PROVIDER');
    $raw = is_string($env) && trim($env) !== '' ? $env : (string) (($cfg['billing']['provider'] ?? 'stripe'));
    $raw = strtolower(trim($raw));
    return $raw === 'square' ? 'square' : 'stripe';
}


function simko_usage_free_limit(): int
{
    return 5;
}

function simko_usage_trial_bonus(): int
{
    return 30;
}

function simko_usage_count(int $userId): int
{
    $stmt = simko_db()->prepare('SELECT COUNT(*) FROM usage_events WHERE user_id = ?');
    $stmt->execute([$userId]);
    return (int) $stmt->fetchColumn();
}

function simko_subscription(int $userId): array
{
    $stmt = simko_db()->prepare(
        'SELECT status, trial_until, square_link_id, stripe_customer_id, stripe_subscription_id, stripe_session_id, updated_at
         FROM subscriptions WHERE user_id = ?'
    );
    $stmt->execute([$userId]);
    $row = $stmt->fetch();
    if (!$row) {
        return [
            'status' => 'free',
            'trial_until' => 0,
            'square_link_id' => '',
            'stripe_customer_id' => '',
            'stripe_subscription_id' => '',
            'stripe_session_id' => '',
            'updated_at' => 0,
        ];
    }
    return [
        'status' => (string) $row['status'],
        'trial_until' => (int) $row['trial_until'],
        'square_link_id' => (string) ($row['square_link_id'] ?? ''),
        'stripe_customer_id' => (string) ($row['stripe_customer_id'] ?? ''),
        'stripe_subscription_id' => (string) ($row['stripe_subscription_id'] ?? ''),
        'stripe_session_id' => (string) ($row['stripe_session_id'] ?? ''),
        'updated_at' => (int) $row['updated_at'],
    ];
}

function simko_subscription_save(int $userId, array $fields): void
{
    $current = simko_subscription($userId);
    $status = (string) ($fields['status'] ?? $current['status']);
    if ($status === '') {
        $status = 'free';
    }
    $trialUntil = array_key_exists('trial_until', $fields) ? (int) $fields['trial_until'] : (int) $current['trial_until'];
    $squareLink = array_key_exists('square_link_id', $fields)
        ? (string) $fields['square_link_id']
        : (string) $current['square_link_id'];
    $customer = array_key_exists('stripe_customer_id', $fields)
        ? (string) $fields['stripe_customer_id']
        : (string) $current['stripe_customer_id'];
    $subscription = array_key_exists('stripe_subscription_id', $fields)
        ? (string) $fields['stripe_subscription_id']
        : (string) $current['stripe_subscription_id'];
    $session = array_key_exists('stripe_session_id', $fields)
        ? (string) $fields['stripe_session_id']
        : (string) $current['stripe_session_id'];
    if ($customer === '' && $current['stripe_customer_id'] !== '') {
        $customer = $current['stripe_customer_id'];
    }
    if ($subscription === '' && $current['stripe_subscription_id'] !== '') {
        $subscription = $current['stripe_subscription_id'];
    }
    if ($session === '' && $current['stripe_session_id'] !== '') {
        $session = $current['stripe_session_id'];
    }
    $stmt = simko_db()->prepare(
        'INSERT INTO subscriptions (
            user_id, status, trial_until, square_link_id, stripe_customer_id, stripe_subscription_id, stripe_session_id, updated_at
         ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(user_id) DO UPDATE SET
            status = excluded.status,
            trial_until = excluded.trial_until,
            square_link_id = excluded.square_link_id,
            stripe_customer_id = excluded.stripe_customer_id,
            stripe_subscription_id = excluded.stripe_subscription_id,
            stripe_session_id = excluded.stripe_session_id,
            updated_at = excluded.updated_at'
    );
    $stmt->execute([$userId, $status, $trialUntil, $squareLink, $customer, $subscription, $session, time()]);
}

function simko_images_daily_cap(): int
{
    $cap = (int) (simko_config_or_empty()['images_daily_cap'] ?? 10);
    return max(0, min($cap, 50));
}

function simko_images_today(int $userId): int
{
    $stmt = simko_db()->prepare('SELECT COUNT(*) FROM generated_images WHERE user_id = ? AND created_at > ?');
    $stmt->execute([$userId, time() - 86400]);
    return (int) $stmt->fetchColumn();
}

// Pictures are paid-only, even while the paywall is off, and capped per person per day.
// Free accounts get 5 text messages and no pictures.
function simko_images_allowed(int $userId): bool
{
    if (simko_subscription($userId)['status'] !== 'paid') {
        return false;
    }
    return simko_images_today($userId) < simko_images_daily_cap();
}

function simko_usage_snapshot(int $userId): array
{
    $used = simko_usage_count($userId);
    $sub = simko_subscription($userId);
    $trial = $sub['status'] === 'trial' && $sub['trial_until'] > time();
    $paid = $sub['status'] === 'paid';
    $limit = $paid ? 0 : simko_usage_free_limit() + ($trial ? simko_usage_trial_bonus() : 0);
    $allowed = $paid || $used < $limit;
    if ($paid) {
        $status = 'paid';
    } elseif ($trial) {
        $status = 'trial';
    } elseif ($sub['status'] === 'past_due') {
        $status = 'past_due';
    } else {
        $status = 'free';
    }
    return [
        'used' => $used,
        'limit' => $paid ? null : $limit,
        'remaining' => $paid ? null : max(0, $limit - $used),
        'allowed' => $allowed,
        'status' => $status,
        'trial_until' => $sub['trial_until'],
    ];
}

function simko_usage_gate(int $userId): array
{
    if (!simko_flag('paywall')) {
        return ['allowed' => true, 'enforced' => false];
    }
    $snap = simko_usage_snapshot($userId);
    $snap['enforced'] = true;
    return $snap;
}

function simko_usage_record(int $userId, string $kind): void
{
    if (!simko_flag('paywall')) {
        return;
    }
    if (!in_array($kind, ['message', 'voice'], true)) {
        $kind = 'message';
    }
    $stmt = simko_db()->prepare('INSERT INTO usage_events (user_id, kind, created_at) VALUES (?, ?, ?)');
    $stmt->execute([$userId, $kind, time()]);
}

function simko_usage_events(int $userId): array
{
    $stmt = simko_db()->prepare(
        'SELECT kind, created_at FROM usage_events WHERE user_id = ? ORDER BY id DESC LIMIT 50'
    );
    $stmt->execute([$userId]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = ['kind' => $row['kind'], 'created_at' => (int) $row['created_at']];
    }
    return $rows;
}

function simko_square_settings(): array
{
    $raw = simko_config_or_empty()['square'] ?? [];
    if (!is_array($raw)) {
        $raw = [];
    }
    $token = trim((string) ($raw['access_token'] ?? ''));
    $connected = $token !== '' && !str_contains($token, 'REPLACE');
    return [
        'environment' => (string) ($raw['environment'] ?? 'sandbox'),
        'application_id' => trim((string) ($raw['application_id'] ?? '')),
        'location_id' => trim((string) ($raw['location_id'] ?? '')),
        'access_token' => $connected ? $token : '',
        'connected' => $connected,
        'api_base' => rtrim((string) ($raw['api_base'] ?? 'https://connect.squareupsandbox.com'), '/'),
        'plan_label' => simko_plan_label(),
    ];
}

function simko_square_checkout(int $userId): array
{
    $square = simko_square_settings();
    if (!$square['connected']) {
        return ['connected' => false, 'error' => 'Square is not connected yet. Nothing was charged.'];
    }
    $payload = json_encode([
        'idempotency_key' => bin2hex(random_bytes(16)),
        'order' => [
            'location_id' => $square['location_id'] !== '' ? $square['location_id'] : 'sandbox-location',
            'line_items' => [[
                'name' => simko_plan_name(),
                'quantity' => '1',
                'base_price_money' => ['amount' => simko_plan_amount(), 'currency' => 'USD'],
            ]],
        ],
        'checkout_options' => ['redirect_url' => rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/') . '/'],
        'payment_note' => 'user ' . $userId,
    ], JSON_UNESCAPED_UNICODE);
    $ch = curl_init($square['api_base'] . '/v2/online-checkout/payment-links');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $payload,
        CURLOPT_HTTPHEADER => [
            'Content-Type: application/json',
            'Authorization: Bearer ' . $square['access_token'],
            'Accept: application/json',
        ],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
        CURLOPT_FOLLOWLOCATION => false,
    ]);
    $raw = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    $data = is_string($raw) ? json_decode($raw, true) : null;
    $link = is_array($data) ? ($data['payment_link'] ?? null) : null;
    if ($code >= 400 || !is_array($link) || empty($link['url']) || empty($link['id'])) {
        return ['connected' => true, 'error' => 'Square did not open a checkout. Nothing was charged.'];
    }
    simko_subscription_save($userId, [
        'status' => simko_subscription($userId)['status'] === 'paid' ? 'paid' : 'free',
        'square_link_id' => (string) $link['id'],
    ]);
    return ['connected' => true, 'url' => (string) $link['url'], 'id' => (string) $link['id']];
}

function simko_square_confirm(int $userId, string $linkId): array
{
    $square = simko_square_settings();
    $sub = simko_subscription($userId);
    if ($linkId === '') {
        $linkId = $sub['square_link_id'];
    }
    if (!$square['connected'] || $linkId === '' || $linkId !== $sub['square_link_id']) {
        return ['paid' => false, 'error' => 'That checkout is not on this account.'];
    }
    $ch = curl_init($square['api_base'] . '/v2/online-checkout/payment-links/' . rawurlencode($linkId));
    curl_setopt_array($ch, [
        CURLOPT_HTTPHEADER => [
            'Authorization: Bearer ' . $square['access_token'],
            'Accept: application/json',
        ],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
    ]);
    $raw = curl_exec($ch);
    curl_close($ch);
    $data = is_string($raw) ? json_decode($raw, true) : null;
    $paid = is_array($data) && !empty($data['payment_link']['paid']);
    if (!$paid) {
        return ['paid' => false, 'error' => 'Square has not taken a payment. Nothing was charged.'];
    }
    simko_subscription_save($userId, ['status' => 'paid']);
    return ['paid' => true];
}

function simko_usage_start_trial(int $userId): array
{
    $sub = simko_subscription($userId);
    if ($sub['status'] === 'paid') {
        return simko_usage_snapshot($userId);
    }
    if ($sub['status'] === 'trial') {
        simko_fail(400, 'The free trial is already on this account.');
    }
    $until = time() + 7 * 24 * 3600;
    simko_subscription_save($userId, ['status' => 'trial', 'trial_until' => $until]);
    return simko_usage_snapshot($userId);
}
