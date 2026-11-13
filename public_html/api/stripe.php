<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';

function simko_config_secret(array $section, string $key, string $envName): string
{
    $env = getenv($envName);
    if (is_string($env) && trim($env) !== '') {
        return trim($env);
    }
    return trim((string) ($section[$key] ?? ''));
}

function simko_secret_is_usable(string $value): bool
{
    if ($value === '' || str_contains($value, 'REPLACE') || preg_match('/changeme|your[_-]?key/i', $value)) {
        return false;
    }
    return true;
}

function simko_stripe_settings(): array
{
    $raw = simko_config_or_empty()['stripe'] ?? [];
    if (!is_array($raw)) {
        $raw = [];
    }
    $restricted = simko_config_secret($raw, 'restricted_key', 'STRIPE_RESTRICTED_KEY');
    $secret = simko_config_secret($raw, 'secret_key', 'STRIPE_SECRET_KEY');
    $key = simko_secret_is_usable($restricted) ? $restricted : (simko_secret_is_usable($secret) ? $secret : '');
    $priceId = simko_config_secret($raw, 'price_id', 'STRIPE_PRICE_ID');
    if (!simko_secret_is_usable($priceId)) {
        $priceId = '';
    }
    $webhook = simko_config_secret($raw, 'webhook_secret', 'STRIPE_WEBHOOK_SECRET');
    if (!simko_secret_is_usable($webhook)) {
        $webhook = '';
    }
    $apiBase = simko_config_secret($raw, 'api_base', 'STRIPE_API_BASE');
    if ($apiBase === '') {
        $apiBase = 'https://api.stripe.com';
    }
    $version = trim((string) ($raw['api_version'] ?? '2026-09-30.endive'));
    if ($version === '') {
        $version = '2026-09-30.endive';
    }
    return [
        'secret_key' => $key,
        'webhook_secret' => $webhook,
        'price_id' => $priceId,
        'api_base' => rtrim($apiBase, '/'),
        'api_version' => $version,
        'connected' => $key !== '' && $priceId !== '',
    ];
}

function simko_stripe_random_letters(int $count = 8): string
{
    $letters = 'abcdefghijklmnopqrstuvwxyz';
    $out = '';
    for ($i = 0; $i < $count; $i++) {
        $out .= $letters[random_int(0, 25)];
    }
    return $out;
}

function simko_stripe_checkout_params(int $userId, array $user): array
{
    $settings = simko_stripe_settings();
    $site = rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/');
    $sub = simko_subscription($userId);
    $params = [
        'mode' => 'subscription',
        'line_items' => [
            ['price' => $settings['price_id'], 'quantity' => 1],
        ],
        'success_url' => $site . '/?billing=success&session_id={CHECKOUT_SESSION_ID}',
        'cancel_url' => $site . '/?billing=cancel',
        'client_reference_id' => (string) $userId,
        'metadata' => ['user_id' => (string) $userId],
        'subscription_data' => [
            'metadata' => ['user_id' => (string) $userId],
        ],
        'integration_identifier' => 'simkosi-' . simko_stripe_random_letters(8),
    ];
    $customerId = (string) ($sub['stripe_customer_id'] ?? '');
    if ($customerId !== '') {
        $params['customer'] = $customerId;
    } else {
        $email = trim((string) ($user['email'] ?? ''));
        if ($email !== '') {
            $params['customer_email'] = $email;
        }
    }
    return $params;
}

function simko_stripe_request(string $path, array $params, ?string $idempotencyKey = null): array
{
    $settings = simko_stripe_settings();
    $headers = [
        'Authorization: Bearer ' . $settings['secret_key'],
        'Content-Type: application/x-www-form-urlencoded',
        'Accept: application/json',
        'Stripe-Version: ' . $settings['api_version'],
        'Idempotency-Key: ' . ($idempotencyKey ?? bin2hex(random_bytes(16))),
    ];
    $body = http_build_query($params);
    $body = str_replace('%7BCHECKOUT_SESSION_ID%7D', '{CHECKOUT_SESSION_ID}', $body);
    return simko_curl(
        $settings['api_base'] . $path,
        $body,
        $headers,
        20
    );
}

function simko_stripe_checkout(int $userId, array $user): array
{
    $settings = simko_stripe_settings();
    if (!$settings['connected']) {
        return ['connected' => false, 'error' => 'Stripe is not connected yet. Nothing was charged.'];
    }
    $params = simko_stripe_checkout_params($userId, $user);
    $result = simko_stripe_request('/v1/checkout/sessions', $params);
    $data = json_decode($result['body'], true);
    $url = is_array($data) ? trim((string) ($data['url'] ?? '')) : '';
    $id = is_array($data) ? trim((string) ($data['id'] ?? '')) : '';
    if ($result['code'] >= 400 || $result['code'] === 0 || $url === '' || $id === '') {
        return ['connected' => true, 'error' => 'Stripe did not open a checkout. Nothing was charged.'];
    }
    simko_subscription_save($userId, [
        'stripe_session_id' => $id,
    ]);
    return ['connected' => true, 'url' => $url, 'id' => $id, 'provider' => 'stripe'];
}

function simko_stripe_portal(int $userId): array
{
    $settings = simko_stripe_settings();
    if (!$settings['connected']) {
        return ['connected' => false, 'error' => 'Stripe is not connected yet. Nothing was charged.'];
    }
    $sub = simko_subscription($userId);
    $customerId = (string) ($sub['stripe_customer_id'] ?? '');
    if ($customerId === '') {
        return ['connected' => true, 'error' => 'There is no Stripe customer on this account yet.'];
    }
    $site = rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/');
    $result = simko_stripe_request('/v1/billing_portal/sessions', [
        'customer' => $customerId,
        'return_url' => $site . '/',
    ]);
    $data = json_decode($result['body'], true);
    $url = is_array($data) ? trim((string) ($data['url'] ?? '')) : '';
    if ($result['code'] >= 400 || $result['code'] === 0 || $url === '') {
        return ['connected' => true, 'error' => 'Stripe did not open the billing portal.'];
    }
    return ['connected' => true, 'url' => $url, 'provider' => 'stripe'];
}

function simko_stripe_verify_signature(string $payload, string $header, string $secret, int $tolerance = 300, ?int $now = null): bool
{
    if ($payload === '' || $header === '' || $secret === '') {
        return false;
    }
    $now = $now ?? time();
    $timestamp = null;
    $signatures = [];
    foreach (explode(',', $header) as $part) {
        $part = trim($part);
        if ($part === '' || !str_contains($part, '=')) {
            continue;
        }
        [$name, $value] = explode('=', $part, 2);
        if ($name === 't') {
            $timestamp = $value;
        } elseif ($name === 'v1') {
            $signatures[] = $value;
        }
    }
    if ($timestamp === null || $signatures === [] || !ctype_digit((string) $timestamp)) {
        return false;
    }
    $ts = (int) $timestamp;
    if (abs($now - $ts) > $tolerance) {
        return false;
    }
    $expected = hash_hmac('sha256', $ts . '.' . $payload, $secret);
    foreach ($signatures as $signature) {
        if (hash_equals($expected, $signature)) {
            return true;
        }
    }
    return false;
}

function simko_stripe_object_id(mixed $value): string
{
    if (is_string($value) && $value !== '') {
        return $value;
    }
    if (is_array($value) && isset($value['id']) && is_string($value['id'])) {
        return $value['id'];
    }
    return '';
}

function simko_stripe_invoice_subscription_id(array $invoice): string
{
    $direct = simko_stripe_object_id($invoice['subscription'] ?? null);
    if ($direct !== '') {
        return $direct;
    }
    $parent = $invoice['parent'] ?? null;
    if (is_array($parent)) {
        $details = $parent['subscription_details'] ?? null;
        if (is_array($details)) {
            return simko_stripe_object_id($details['subscription'] ?? null);
        }
    }
    return '';
}

function simko_stripe_find_user_id(array $object, string $customerId = '', string $subscriptionId = ''): int
{
    $meta = $object['metadata']['user_id'] ?? $object['client_reference_id'] ?? '';
    $fromMeta = (int) $meta;
    if ($fromMeta > 0) {
        return $fromMeta;
    }
    $customerId = $customerId !== '' ? $customerId : simko_stripe_object_id($object['customer'] ?? null);
    $subscriptionId = $subscriptionId !== '' ? $subscriptionId : simko_stripe_object_id($object['subscription'] ?? null);
    if ($subscriptionId !== '') {
        $stmt = simko_db()->prepare('SELECT user_id FROM subscriptions WHERE stripe_subscription_id = ?');
        $stmt->execute([$subscriptionId]);
        $row = $stmt->fetch();
        if ($row) {
            return (int) $row['user_id'];
        }
    }
    if ($customerId !== '') {
        $stmt = simko_db()->prepare('SELECT user_id FROM subscriptions WHERE stripe_customer_id = ?');
        $stmt->execute([$customerId]);
        $row = $stmt->fetch();
        if ($row) {
            return (int) $row['user_id'];
        }
    }
    return 0;
}

function simko_stripe_event_seen(string $eventId): bool
{
    $stmt = simko_db()->prepare('SELECT event_id FROM stripe_events WHERE event_id = ?');
    $stmt->execute([$eventId]);
    return (bool) $stmt->fetch();
}

function simko_stripe_event_mark(string $eventId, string $type): void
{
    $stmt = simko_db()->prepare(
        'INSERT OR IGNORE INTO stripe_events (event_id, event_type, processed_at) VALUES (?, ?, ?)'
    );
    $stmt->execute([$eventId, $type, time()]);
}

function simko_stripe_status_from_subscription(string $stripeStatus): string
{
    return match ($stripeStatus) {
        'active', 'trialing' => 'paid',
        'past_due', 'unpaid', 'paused' => 'past_due',
        default => 'free',
    };
}

function simko_stripe_handle_checkout_session(array $session, bool $requirePaid): void
{
    $payment = (string) ($session['payment_status'] ?? '');
    if ($requirePaid && !in_array($payment, ['paid', 'no_payment_required'], true)) {
        return;
    }
    $userId = simko_stripe_find_user_id($session);
    if ($userId < 1) {
        return;
    }
    simko_subscription_save($userId, [
        'status' => 'paid',
        'stripe_customer_id' => simko_stripe_object_id($session['customer'] ?? null),
        'stripe_subscription_id' => simko_stripe_object_id($session['subscription'] ?? null),
        'stripe_session_id' => simko_stripe_object_id($session['id'] ?? null),
    ]);
}

function simko_stripe_handle_subscription(array $subscription, ?string $forcedStatus = null): void
{
    $userId = simko_stripe_find_user_id($subscription);
    if ($userId < 1) {
        return;
    }
    $status = $forcedStatus ?? simko_stripe_status_from_subscription((string) ($subscription['status'] ?? ''));
    simko_subscription_save($userId, [
        'status' => $status,
        'stripe_customer_id' => simko_stripe_object_id($subscription['customer'] ?? null),
        'stripe_subscription_id' => simko_stripe_object_id($subscription['id'] ?? null),
    ]);
}

function simko_stripe_handle_event(array $event): array
{
    $eventId = trim((string) ($event['id'] ?? ''));
    $type = trim((string) ($event['type'] ?? ''));
    if ($eventId === '' || $type === '') {
        return ['ok' => false, 'error' => 'That event is missing an id or type.'];
    }
    if (simko_stripe_event_seen($eventId)) {
        return ['ok' => true, 'duplicate' => true, 'type' => $type];
    }
    $object = $event['data']['object'] ?? null;
    if (!is_array($object)) {
        return ['ok' => false, 'error' => 'That event has no object.'];
    }
    switch ($type) {
        case 'checkout.session.completed':
            simko_stripe_handle_checkout_session($object, true);
            break;
        case 'checkout.session.async_payment_succeeded':
            simko_stripe_handle_checkout_session($object, true);
            break;
        case 'customer.subscription.updated':
            simko_stripe_handle_subscription($object);
            break;
        case 'customer.subscription.deleted':
            simko_stripe_handle_subscription($object, 'free');
            break;
        case 'invoice.payment_failed':
            $userId = simko_stripe_find_user_id(
                $object,
                simko_stripe_object_id($object['customer'] ?? null),
                simko_stripe_invoice_subscription_id($object)
            );
            if ($userId > 0) {
                simko_subscription_save($userId, [
                    'status' => 'past_due',
                    'stripe_customer_id' => simko_stripe_object_id($object['customer'] ?? null),
                    'stripe_subscription_id' => simko_stripe_invoice_subscription_id($object),
                ]);
            }
            break;
        default:
            break;
    }
    simko_stripe_event_mark($eventId, $type);
    return ['ok' => true, 'type' => $type];
}
