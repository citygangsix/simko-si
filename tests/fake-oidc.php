<?php
declare(strict_types=1);

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
header('Content-Type: application/json; charset=utf-8');
if ($path === '/token') {
    parse_str((string) file_get_contents('php://input'), $form);
    $code = (string) ($form['code'] ?? '');
    $access = $code === 'unverified' ? 'oidc-unverified' : ($code === 'noflag' ? 'oidc-noflag' : 'oidc-access');
    echo json_encode(['access_token' => $access, 'token_type' => 'Bearer']);
    return true;
}
if ($path === '/userinfo') {
    $auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
    if (str_contains($auth, 'oidc-unverified')) {
        echo json_encode(['sub' => 'google-subject-2', 'email' => 'ada@simkosi.test', 'email_verified' => false]);
    } elseif (str_contains($auth, 'oidc-noflag')) {
        echo json_encode(['sub' => 'google-subject-3', 'email' => 'ada@simkosi.test']);
    } else {
        echo json_encode(['sub' => 'google-subject-1', 'email' => 'ada@simkosi.test', 'email_verified' => true]);
    }
    return true;
}
http_response_code(404);
echo json_encode(['error' => 'no']);
return true;
