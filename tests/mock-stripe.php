<?php
declare(strict_types=1);

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
$body = file_get_contents('php://input');
$body = is_string($body) ? $body : '';
parse_str($body, $fields);
$dump = getenv('SIMKO_STRIPE_CAPTURE');
if (is_string($dump) && $dump !== '') {
    file_put_contents($dump, json_encode([
        'method' => $method,
        'path' => $path,
        'headers' => [
            'authorization' => (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? ''),
            'stripe_version' => (string) ($_SERVER['HTTP_STRIPE_VERSION'] ?? ''),
            'idempotency_key' => (string) ($_SERVER['HTTP_IDEMPOTENCY_KEY'] ?? ''),
            'content_type' => (string) ($_SERVER['CONTENT_TYPE'] ?? ''),
        ],
        'fields' => $fields,
        'raw' => $body,
    ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
}

header('Content-Type: application/json; charset=utf-8');

if ($method === 'POST' && $path === '/v1/checkout/sessions') {
    $id = 'cs_test_mock_session';
    echo json_encode([
        'id' => $id,
        'object' => 'checkout.session',
        'mode' => 'subscription',
        'url' => 'http://127.0.0.1/mock-stripe-checkout/' . $id,
        'payment_status' => 'unpaid',
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/billing_portal/sessions') {
    echo json_encode([
        'id' => 'bps_test_mock_portal',
        'object' => 'billing_portal.session',
        'url' => 'http://127.0.0.1/mock-stripe-portal/bps_test_mock_portal',
    ]);
    return;
}

http_response_code(404);
echo json_encode(['error' => ['message' => 'unknown mock path', 'path' => $path]]);
