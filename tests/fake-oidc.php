<?php
declare(strict_types=1);

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
header('Content-Type: application/json; charset=utf-8');
if ($path === '/token') {
    echo json_encode(['access_token' => 'oidc-access', 'token_type' => 'Bearer']);
    return true;
}
if ($path === '/userinfo') {
    echo json_encode(['sub' => 'google-subject-1', 'email' => 'ada@simkosi.test']);
    return true;
}
http_response_code(404);
echo json_encode(['error' => 'no']);
return true;
