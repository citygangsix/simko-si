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

$journal = getenv('SIMKO_STRIPE_LOG');
if (is_string($journal) && $journal !== '') {
    file_put_contents($journal, json_encode([
        'method' => $method,
        'path' => $path,
        'idempotency_key' => (string) ($_SERVER['HTTP_IDEMPOTENCY_KEY'] ?? ''),
        'authorization' => (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? ''),
        'fields' => $fields,
    ], JSON_UNESCAPED_SLASHES) . "\n", FILE_APPEND | LOCK_EX);
}

header('Content-Type: application/json; charset=utf-8');

$fail = getenv('SIMKO_STRIPE_FAIL');
if (is_string($fail) && $fail !== '' && is_file($fail) && str_contains((string) file_get_contents($fail), $path)) {
    http_response_code(500);
    echo json_encode(['error' => ['message' => 'mock failure', 'path' => $path]]);
    return;
}

// Billing meter events (metered picture usage): https://docs.stripe.com/api/billing/meter-event/create
if ($method === 'POST' && $path === '/v1/billing/meter_events') {
    if (($fields['event_name'] ?? '') === '' || ($fields['payload']['stripe_customer_id'] ?? '') === '' || ($fields['payload']['value'] ?? '') === '') {
        http_response_code(400);
        echo json_encode(['error' => ['message' => 'event_name, payload[stripe_customer_id] and payload[value] are required']]);
        return;
    }
    echo json_encode([
        'object' => 'billing.meter_event',
        'event_name' => $fields['event_name'],
        'identifier' => (string) ($fields['identifier'] ?? 'mock_identifier'),
        'livemode' => false,
        'payload' => $fields['payload'],
        'timestamp' => (int) ($fields['timestamp'] ?? time()),
    ]);
    return;
}

// Monthly picture invoice: create the draft, add one item, finalize.
if ($method === 'POST' && $path === '/v1/invoices') {
    echo json_encode([
        'id' => 'in_test_' . substr(sha1((string) ($_SERVER['HTTP_IDEMPOTENCY_KEY'] ?? $body)), 0, 12),
        'object' => 'invoice',
        'status' => 'draft',
        'customer' => (string) ($fields['customer'] ?? ''),
        'metadata' => $fields['metadata'] ?? [],
    ]);
    return;
}
if ($method === 'POST' && $path === '/v1/invoiceitems') {
    echo json_encode([
        'id' => 'ii_test_' . substr(sha1((string) ($_SERVER['HTTP_IDEMPOTENCY_KEY'] ?? $body)), 0, 12),
        'object' => 'invoiceitem',
        'amount' => (int) ($fields['amount'] ?? 0),
        'currency' => (string) ($fields['currency'] ?? ''),
        'invoice' => (string) ($fields['invoice'] ?? ''),
    ]);
    return;
}
if ($method === 'POST' && preg_match('#^/v1/invoices/(in_[A-Za-z0-9_]+)/finalize$#', $path, $m)) {
    echo json_encode(['id' => $m[1], 'object' => 'invoice', 'status' => 'open']);
    return;
}

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
