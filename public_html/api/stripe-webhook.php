<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/stripe.php';

$method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
if ($method !== 'POST') {
    simko_fail(405, 'Stripe webhooks are posted.');
}

$payload = file_get_contents('php://input');
$payload = is_string($payload) ? $payload : '';
$header = (string) ($_SERVER['HTTP_STRIPE_SIGNATURE'] ?? '');
$secret = simko_stripe_settings()['webhook_secret'];
if ($secret === '') {
    simko_fail(503, 'Stripe webhooks are not configured.');
}
if (!simko_stripe_verify_signature($payload, $header, $secret)) {
    simko_fail(400, 'The Stripe signature is not valid.');
}
$event = json_decode($payload, true);
if (!is_array($event)) {
    simko_fail(400, 'That webhook is not valid JSON.');
}
$result = simko_stripe_handle_event($event);
if (empty($result['ok'])) {
    simko_fail(400, (string) ($result['error'] ?? 'That webhook could not be applied.'));
}
simko_ok($result);
