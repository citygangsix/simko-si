<?php
declare(strict_types=1);

function apple_b64(string $raw): string
{
    return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
}

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$keyPath = (string) getenv('SIMKO_APPLE_KEY');
$kid = (string) getenv('SIMKO_APPLE_KID');
$key = openssl_pkey_get_private((string) file_get_contents($keyPath));
$details = openssl_pkey_get_details($key);

if ($path === '/auth/keys') {
    header('Content-Type: application/json');
    echo json_encode(['keys' => [[
        'kty' => 'RSA',
        'kid' => $kid,
        'use' => 'sig',
        'alg' => 'RS256',
        'n' => apple_b64($details['rsa']['n']),
        'e' => apple_b64($details['rsa']['e']),
    ]]]);
    return true;
}

if ($path === '/auth/token') {
    $raw = file_get_contents('php://input') ?: '';
    $capture = (string) getenv('SIMKO_APPLE_CAPTURE');
    if ($capture !== '') {
        file_put_contents($capture, $raw);
    }
    $mode = trim((string) @file_get_contents((string) getenv('SIMKO_APPLE_MODE_FILE')));
    if ($mode === '') {
        $mode = 'ok';
    }
    $db = new PDO('sqlite:' . getenv('SIMKO_APPLE_DB'));
    $nonce = (string) $db->query('SELECT nonce FROM oauth_states ORDER BY created_at DESC LIMIT 1')->fetchColumn();
    if ($mode === 'badnonce') {
        $nonce = 'wrong-nonce';
    }
    $claims = [
        'iss' => 'https://appleid.apple.com',
        'aud' => $mode === 'badaud' ? 'wrong-services-id' : (string) getenv('SIMKO_APPLE_AUD'),
        'sub' => 'apple-subject-1',
        'email' => 'ada@privaterelay.appleid.com',
        'is_private_email' => true,
        'nonce' => $nonce,
        'exp' => $mode === 'expired' ? time() - 30 : time() + 600,
    ];
    $header = apple_b64((string) json_encode(['alg' => 'RS256', 'kid' => $kid]));
    $body = apple_b64((string) json_encode($claims));
    $sig = '';
    openssl_sign($header . '.' . $body, $sig, $key, OPENSSL_ALGO_SHA256);
    header('Content-Type: application/json');
    echo json_encode([
        'access_token' => 'apple-access',
        'id_token' => $header . '.' . $body . '.' . apple_b64($sig),
        'token_type' => 'Bearer',
    ]);
    return true;
}

http_response_code(404);
echo 'no';
return true;
