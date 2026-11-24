<?php
declare(strict_types=1);

// Fake browser push service. Checks the VAPID JWT (ES256) against SIMKO_VAPID_PUB, decrypts the
// RFC 8291 aes128gcm body with the browser key SIMKO_UA_PEM + SIMKO_UA_AUTH, and logs one JSON line.
// /push/gone answers 410 like a dead subscription.
function fp_b64d(string $t): string { $t = strtr($t, '-_', '+/'); return (string) base64_decode($t . str_repeat('=', (4 - strlen($t) % 4) % 4)); }
function fp_der_int(string $b): string { $b = ltrim($b, "\0"); if ($b === '' || (ord($b[0]) & 0x80)) { $b = "\0" . $b; } return "\x02" . chr(strlen($b)) . $b; }
$log = (string) getenv('SIMKO_PUSH_LOG');
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$entry = ['path' => $path, 'jwt_ok' => false, 'payload' => null, 'encoding' => $_SERVER['HTTP_CONTENT_ENCODING'] ?? '', 'ttl' => $_SERVER['HTTP_TTL'] ?? ''];
if ($path === '/push/gone') {
    file_put_contents($log, json_encode($entry) . "\n", FILE_APPEND);
    http_response_code(410);
    return true;
}
$auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
if (preg_match('/^vapid t=([^,]+), k=(\S+)$/', $auth, $m) && $m[2] === getenv('SIMKO_VAPID_PUB')) {
    [$h, $p, $s] = explode('.', $m[1]);
    $claims = json_decode(fp_b64d($p), true);
    $raw = fp_b64d($s);
    $seq = fp_der_int(substr($raw, 0, 32)) . fp_der_int(substr($raw, 32));
    $der = "\x30" . chr(strlen($seq)) . $seq;
    $pub = "-----BEGIN PUBLIC KEY-----\n" . chunk_split(base64_encode(hex2bin('3059301306072a8648ce3d020106082a8648ce3d030107034200') . fp_b64d($m[2])), 64, "\n") . "-----END PUBLIC KEY-----\n";
    $entry['jwt_ok'] = openssl_verify($h . '.' . $p, $der, $pub, OPENSSL_ALGO_SHA256) === 1
        && ($claims['aud'] ?? '') === 'http://' . $_SERVER['HTTP_HOST'] && ($claims['exp'] ?? 0) > time()
        && str_starts_with((string) ($claims['sub'] ?? ''), 'mailto:');
}
$body = file_get_contents('php://input') ?: '';
if (strlen($body) > 86 + 16) {
    $salt = substr($body, 0, 16);
    $asPub = substr($body, 21, 65);
    $cipher = substr($body, 86, -16);
    $tag = substr($body, -16);
    $ua = openssl_pkey_get_private((string) getenv('SIMKO_UA_PEM'));
    $d = openssl_pkey_get_details($ua);
    $uaPub = "\x04" . str_pad($d['ec']['x'], 32, "\0", STR_PAD_LEFT) . str_pad($d['ec']['y'], 32, "\0", STR_PAD_LEFT);
    $asKey = openssl_pkey_get_public("-----BEGIN PUBLIC KEY-----\n" . chunk_split(base64_encode(hex2bin('3059301306072a8648ce3d020106082a8648ce3d030107034200') . $asPub), 64, "\n") . "-----END PUBLIC KEY-----\n");
    $shared = openssl_pkey_derive($asKey, $ua, 32);
    $ikm = hash_hkdf('sha256', $shared, 32, "WebPush: info\0" . $uaPub . $asPub, fp_b64d((string) getenv('SIMKO_UA_AUTH')));
    $cek = hash_hkdf('sha256', $ikm, 16, "Content-Encoding: aes128gcm\0", $salt);
    $nonce = hash_hkdf('sha256', $ikm, 12, "Content-Encoding: nonce\0", $salt);
    $plain = openssl_decrypt($cipher, 'aes-128-gcm', $cek, OPENSSL_RAW_DATA, $nonce, $tag);
    if (is_string($plain) && str_ends_with($plain, "\x02")) {
        $entry['payload'] = json_decode(substr($plain, 0, -1), true);
    }
}
file_put_contents($log, json_encode($entry) . "\n", FILE_APPEND);
http_response_code($entry['jwt_ok'] && $entry['payload'] ? 201 : 400);
return true;
