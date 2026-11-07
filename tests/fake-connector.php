<?php
declare(strict_types=1);

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$log = (string) getenv('SIMKO_CONNECTOR_LOG');
$raw = file_get_contents('php://input') ?: '';
if ($log !== '') {
    file_put_contents($log, $path . ' ' . $raw . "\n", FILE_APPEND);
}
parse_str($raw, $form);
header('Content-Type: application/json');
if ($path === '/revoke') {
    echo json_encode(['revoked' => true]);
    return true;
}
if (($form['grant_type'] ?? '') === 'refresh_token') {
    echo json_encode(['access_token' => 'access-refreshed', 'expires_in' => 1200, 'token_type' => 'Bearer']);
    return true;
}
echo json_encode([
    'access_token' => 'access-one',
    'refresh_token' => 'refresh-one',
    'expires_in' => 3600,
    'token_type' => 'Bearer',
]);
return true;
