<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_oauth_config(string $provider): array
{
    $all = simko_config_or_empty()['oauth'] ?? [];
    $row = is_array($all) && isset($all[$provider]) && is_array($all[$provider]) ? $all[$provider] : [];
    $cfg = [
        'client_id' => trim((string) ($row['client_id'] ?? '')),
        'client_secret' => (string) ($row['client_secret'] ?? ''),
        'authorize_url' => trim((string) ($row['authorize_url'] ?? '')),
        'token_url' => trim((string) ($row['token_url'] ?? '')),
        'userinfo_url' => trim((string) ($row['userinfo_url'] ?? '')),
        'redirect_url' => trim((string) ($row['redirect_url'] ?? '')),
        'scope' => trim((string) ($row['scope'] ?? 'openid email')),
        'team_id' => trim((string) ($row['team_id'] ?? '')),
        'key_id' => trim((string) ($row['key_id'] ?? '')),
        'p8_path' => trim((string) ($row['p8_path'] ?? '')),
        'jwks_url' => trim((string) ($row['jwks_url'] ?? 'https://appleid.apple.com/auth/keys')),
    ];
    if ($provider === 'apple') {
        if ($cfg['authorize_url'] === '') {
            $cfg['authorize_url'] = 'https://appleid.apple.com/auth/authorize';
        }
        if ($cfg['token_url'] === '') {
            $cfg['token_url'] = 'https://appleid.apple.com/auth/token';
        }
        if ($cfg['scope'] === '' || $cfg['scope'] === 'openid email') {
            $cfg['scope'] = 'name email';
        }
    }
    return $cfg;
}

function simko_oauth_ready(string $provider): bool
{
    if (!simko_flag('oauth')) {
        return false;
    }
    if ($provider === 'apple') {
        return simko_apple_ready();
    }
    $cfg = simko_oauth_config($provider);
    return $cfg['client_id'] !== '' && !str_contains($cfg['client_id'], 'REPLACE');
}

function simko_apple_ready(): bool
{
    $cfg = simko_oauth_config('apple');
    if ($cfg['client_id'] === '' || str_contains($cfg['client_id'], 'REPLACE')) {
        return false;
    }
    if ($cfg['team_id'] === '' || $cfg['key_id'] === '' || $cfg['p8_path'] === '') {
        return false;
    }
    if (!is_file($cfg['p8_path'])) {
        return false;
    }
    $real = realpath($cfg['p8_path']);
    $private = realpath(simko_private_dir());
    if ($real === false || $private === false || !str_starts_with($real, $private . DIRECTORY_SEPARATOR)) {
        return false;
    }
    return true;
}

// Google returns email_verified as a JSON boolean. Accept only a real true
// (or the string "true" some older endpoints send). Missing means not verified.
function simko_oauth_email_verified($info): bool
{
    if (!is_array($info) || !array_key_exists('email_verified', $info)) {
        return false;
    }
    $flag = $info['email_verified'];
    return $flag === true || (is_string($flag) && strtolower($flag) === 'true');
}

function simko_oauth_start(string $provider): array
{
    if (!in_array($provider, ['google', 'apple'], true)) {
        simko_fail(400, 'That sign-in provider is not offered.');
    }
    if (!simko_oauth_ready($provider)) {
        simko_fail(404, 'That sign-in button is hidden until Joseph registers the app.');
    }
    $cfg = simko_oauth_config($provider);
    $state = bin2hex(random_bytes(16));
    $nonce = $provider === 'apple' ? bin2hex(random_bytes(16)) : '';
    $stmt = simko_db()->prepare('INSERT INTO oauth_states (state, provider, created_at, nonce) VALUES (?, ?, ?, ?)');
    $stmt->execute([$state, $provider, time(), $nonce]);
    $redirect = $cfg['redirect_url'] !== '' ? $cfg['redirect_url'] : rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/') . '/api/oauth/callback';
    $query = [
        'client_id' => $cfg['client_id'],
        'redirect_uri' => $redirect,
        'response_type' => $provider === 'apple' ? 'code id_token' : 'code',
        'scope' => $cfg['scope'],
        'state' => $state,
    ];
    if ($provider === 'apple') {
        $query['response_mode'] = 'form_post';
        $query['nonce'] = $nonce;
    }
    return ['url' => $cfg['authorize_url'] . (str_contains($cfg['authorize_url'], '?') ? '&' : '?') . http_build_query($query), 'state' => $state];
}

function simko_oauth_finish(string $provider, string $code, string $state, array $posted = []): array
{
    if (!simko_oauth_ready($provider) || $code === '' || $state === '') {
        simko_fail(400, 'That sign-in could not be finished.');
    }
    $stmt = simko_db()->prepare('SELECT provider, created_at, nonce FROM oauth_states WHERE state = ?');
    $stmt->execute([$state]);
    $saved = $stmt->fetch();
    if (!$saved || (string) $saved['provider'] !== $provider || (int) $saved['created_at'] < time() - 600) {
        simko_db()->prepare('DELETE FROM oauth_states WHERE state = ?')->execute([$state]);
        simko_fail(400, 'That sign-in expired. Try again.');
    }
    if ($provider === 'apple') {
        $result = simko_apple_finish(simko_oauth_config('apple'), $code, (string) ($saved['nonce'] ?? ''), $posted);
        simko_db()->prepare('DELETE FROM oauth_states WHERE state = ?')->execute([$state]);
        return $result;
    }
    simko_db()->prepare('DELETE FROM oauth_states WHERE state = ?')->execute([$state]);
    $cfg = simko_oauth_config($provider);
    $redirect = $cfg['redirect_url'] !== '' ? $cfg['redirect_url'] : rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/') . '/api/oauth/callback';
    $body = http_build_query([
        'code' => $code,
        'client_id' => $cfg['client_id'],
        'client_secret' => $cfg['client_secret'],
        'redirect_uri' => $redirect,
        'grant_type' => 'authorization_code',
    ]);
    $ch = curl_init($cfg['token_url']);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded', 'Accept: application/json'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
    ]);
    $raw = curl_exec($ch);
    curl_close($ch);
    $token = is_string($raw) ? json_decode($raw, true) : null;
    $access = is_array($token) ? (string) ($token['access_token'] ?? '') : '';
    if ($access === '') {
        simko_fail(401, 'That sign-in was not accepted.');
    }
    $ch = curl_init($cfg['userinfo_url']);
    curl_setopt_array($ch, [
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $access, 'Accept: application/json'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
    ]);
    $infoRaw = curl_exec($ch);
    curl_close($ch);
    $info = is_string($infoRaw) ? json_decode($infoRaw, true) : null;
    $sub = is_array($info) ? trim((string) ($info['sub'] ?? '')) : '';
    $email = is_array($info) ? strtolower(trim((string) ($info['email'] ?? ''))) : '';
    if ($sub === '' || !filter_var($email, FILTER_VALIDATE_EMAIL)) {
        simko_fail(401, 'That sign-in did not include an email.');
    }
    if ($provider === 'google' && !simko_oauth_email_verified($info)) {
        simko_fail(403, 'Google has not verified that email address, so Simko SI cannot sign you in with it. Verify the email with Google, or sign in with your email and password.');
    }
    $link = simko_db()->prepare('SELECT user_id FROM oauth_identities WHERE provider = ? AND subject = ?');
    $link->execute([$provider, $sub]);
    $existing = $link->fetch();
    if ($existing) {
        $userId = (int) $existing['user_id'];
    } else {
        $found = simko_db()->prepare('SELECT id FROM users WHERE email = ?');
        $found->execute([$email]);
        $user = $found->fetch();
        if ($user) {
            $userId = (int) $user['id'];
        } else {
            $insert = simko_db()->prepare(
                'INSERT INTO users (email, password_hash, confirmed, confirm_token, created_at, role, parent_consent_at)
                 VALUES (?, ?, 1, NULL, ?, ?, NULL)'
            );
            $insert->execute([$email, password_hash(bin2hex(random_bytes(24)), PASSWORD_DEFAULT), time(), 'adult']);
            $userId = (int) simko_db()->lastInsertId();
        }
        $save = simko_db()->prepare('INSERT INTO oauth_identities (provider, subject, user_id, email_relay, created_at) VALUES (?, ?, ?, 0, ?)');
        $save->execute([$provider, $sub, $userId, time()]);
    }
    $issued = simko_issue_token($userId);
    $emailStmt = simko_db()->prepare('SELECT email FROM users WHERE id = ?');
    $emailStmt->execute([$userId]);
    return ['token' => $issued, 'email' => (string) $emailStmt->fetchColumn()];
}

function simko_apple_finish(array $cfg, string $code, string $nonce, array $posted): array
{
    $redirect = $cfg['redirect_url'] !== '' ? $cfg['redirect_url'] : rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/') . '/api/oauth/callback';
    $secret = simko_apple_client_secret($cfg);
    $body = http_build_query([
        'code' => $code,
        'client_id' => $cfg['client_id'],
        'client_secret' => $secret,
        'redirect_uri' => $redirect,
        'grant_type' => 'authorization_code',
    ]);
    $ch = curl_init($cfg['token_url']);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded', 'Accept: application/json'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
    ]);
    $raw = curl_exec($ch);
    curl_close($ch);
    $token = is_string($raw) ? json_decode($raw, true) : null;
    $idToken = is_array($token) ? (string) ($token['id_token'] ?? '') : '';
    if ($idToken === '') {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    $claims = simko_apple_verify_id_token($idToken, $cfg, $nonce);
    $postedToken = trim((string) ($posted['id_token'] ?? ''));
    if ($postedToken !== '') {
        $postedClaims = simko_apple_verify_id_token($postedToken, $cfg, $nonce);
        if ((string) ($postedClaims['sub'] ?? '') !== (string) $claims['sub']) {
            simko_fail(401, 'Apple did not accept that sign-in.');
        }
    }
    $sub = trim((string) ($claims['sub'] ?? ''));
    $email = strtolower(trim((string) ($claims['email'] ?? '')));
    $userJson = json_decode((string) ($posted['user'] ?? ''), true);
    if ($email === '' && is_array($userJson)) {
        $email = strtolower(trim((string) ($userJson['email'] ?? '')));
    }
    $relay = !empty($claims['is_private_email']) || str_ends_with($email, '@privaterelay.appleid.com');
    if ($sub === '') {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    $link = simko_db()->prepare('SELECT user_id FROM oauth_identities WHERE provider = ? AND subject = ?');
    $link->execute(['apple', $sub]);
    $existing = $link->fetch();
    if ($existing) {
        $userId = (int) $existing['user_id'];
    } else {
        if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
            simko_fail(401, 'Apple did not include an email for this new sign-in.');
        }
        $found = simko_db()->prepare('SELECT id FROM users WHERE email = ?');
        $found->execute([$email]);
        $user = $found->fetch();
        if ($user) {
            $userId = (int) $user['id'];
        } else {
            $insert = simko_db()->prepare(
                'INSERT INTO users (email, password_hash, confirmed, confirm_token, created_at, role, parent_consent_at)
                 VALUES (?, ?, 1, NULL, ?, ?, NULL)'
            );
            $insert->execute([$email, password_hash(bin2hex(random_bytes(24)), PASSWORD_DEFAULT), time(), 'adult']);
            $userId = (int) simko_db()->lastInsertId();
        }
        $save = simko_db()->prepare(
            'INSERT INTO oauth_identities (provider, subject, user_id, email_relay, created_at) VALUES (?, ?, ?, ?, ?)'
        );
        $save->execute(['apple', $sub, $userId, $relay ? 1 : 0, time()]);
    }
    $issued = simko_issue_token($userId);
    $emailStmt = simko_db()->prepare('SELECT email FROM users WHERE id = ?');
    $emailStmt->execute([$userId]);
    return ['token' => $issued, 'email' => (string) $emailStmt->fetchColumn(), 'email_relay' => $relay];
}

function simko_apple_client_secret(array $cfg): string
{
    $pem = @file_get_contents($cfg['p8_path']);
    $key = is_string($pem) ? openssl_pkey_get_private($pem) : false;
    if ($key === false) {
        simko_fail(500, 'Apple sign-in is not configured.');
    }
    $now = time();
    $header = simko_b64url((string) json_encode(['alg' => 'ES256', 'kid' => $cfg['key_id']]));
    $claims = simko_b64url((string) json_encode([
        'iss' => $cfg['team_id'],
        'iat' => $now,
        'exp' => $now + 300,
        'aud' => 'https://appleid.apple.com',
        'sub' => $cfg['client_id'],
    ]));
    $input = $header . '.' . $claims;
    $der = '';
    if (!openssl_sign($input, $der, $key, OPENSSL_ALGO_SHA256)) {
        simko_fail(500, 'Apple sign-in is not configured.');
    }
    return $input . '.' . simko_b64url(simko_ecdsa_der_to_raw($der));
}

function simko_apple_verify_id_token(string $jwt, array $cfg, string $nonce): array
{
    $parts = explode('.', $jwt);
    if (count($parts) !== 3) {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    $header = json_decode(simko_b64url_decode($parts[0]), true);
    $claims = json_decode(simko_b64url_decode($parts[1]), true);
    $sig = simko_b64url_decode($parts[2]);
    if (!is_array($header) || !is_array($claims) || ($header['alg'] ?? '') !== 'RS256' || $sig === '') {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    $pem = simko_apple_jwk_pem((string) ($header['kid'] ?? ''), $cfg['jwks_url']);
    $verified = openssl_verify($parts[0] . '.' . $parts[1], $sig, $pem, OPENSSL_ALGO_SHA256);
    if ($verified !== 1) {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    if (($claims['iss'] ?? '') !== 'https://appleid.apple.com') {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    $aud = $claims['aud'] ?? '';
    $audOk = $aud === $cfg['client_id'] || (is_array($aud) && in_array($cfg['client_id'], $aud, true));
    if (!$audOk || (int) ($claims['exp'] ?? 0) <= time()) {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    if ($nonce === '' || !hash_equals($nonce, (string) ($claims['nonce'] ?? ''))) {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    return $claims;
}

function simko_apple_jwk_pem(string $kid, string $jwksUrl): string
{
    $ch = curl_init($jwksUrl);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 15,
        CURLOPT_HTTPHEADER => ['Accept: application/json'],
    ]);
    $raw = curl_exec($ch);
    curl_close($ch);
    $set = is_string($raw) ? json_decode($raw, true) : null;
    $keys = is_array($set) ? ($set['keys'] ?? []) : [];
    foreach ($keys as $jwk) {
        if (!is_array($jwk) || (string) ($jwk['kid'] ?? '') !== $kid) {
            continue;
        }
        if (($jwk['kty'] ?? '') !== 'RSA' || empty($jwk['n']) || empty($jwk['e'])) {
            continue;
        }
        return simko_rsa_jwk_pem((string) $jwk['n'], (string) $jwk['e']);
    }
    simko_fail(401, 'Apple did not accept that sign-in.');
}

function simko_b64url(string $raw): string
{
    return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
}

function simko_b64url_decode(string $data): string
{
    $data = strtr($data, '-_', '+/');
    $pad = strlen($data) % 4;
    if ($pad !== 0) {
        $data .= str_repeat('=', 4 - $pad);
    }
    $out = base64_decode($data, true);
    return is_string($out) ? $out : '';
}

function simko_ecdsa_der_to_raw(string $der): string
{
    $pos = 0;
    if (ord($der[$pos] ?? "\x00") !== 0x30) {
        simko_fail(500, 'Apple sign-in is not configured.');
    }
    $pos++;
    $seqLen = ord($der[$pos++] ?? "\x00");
    if ($seqLen & 0x80) {
        $n = $seqLen & 0x7f;
        $seqLen = 0;
        for ($i = 0; $i < $n; $i++) {
            $seqLen = ($seqLen << 8) | ord($der[$pos++] ?? "\x00");
        }
    }
    if (ord($der[$pos++] ?? "\x00") !== 0x02) {
        simko_fail(500, 'Apple sign-in is not configured.');
    }
    $rLen = ord($der[$pos++] ?? "\x00");
    $r = substr($der, $pos, $rLen);
    $pos += $rLen;
    if (ord($der[$pos++] ?? "\x00") !== 0x02) {
        simko_fail(500, 'Apple sign-in is not configured.');
    }
    $sLen = ord($der[$pos++] ?? "\x00");
    $s = substr($der, $pos, $sLen);
    $r = ltrim($r, "\x00");
    $s = ltrim($s, "\x00");
    return str_pad($r, 32, "\x00", STR_PAD_LEFT) . str_pad($s, 32, "\x00", STR_PAD_LEFT);
}

function simko_rsa_jwk_pem(string $nB64, string $eB64): string
{
    $n = simko_b64url_decode($nB64);
    $e = simko_b64url_decode($eB64);
    if ($n === '' || $e === '') {
        simko_fail(401, 'Apple did not accept that sign-in.');
    }
    $seq = simko_asn1_int($n) . simko_asn1_int($e);
    $rsa = "\x30" . simko_asn1_len(strlen($seq)) . $seq;
    $algo = hex2bin('300d06092a864886f70d0101010500');
    $bit = "\x03" . simko_asn1_len(strlen($rsa) + 1) . "\x00" . $rsa;
    $spki = "\x30" . simko_asn1_len(strlen($algo) + strlen($bit)) . $algo . $bit;
    return "-----BEGIN PUBLIC KEY-----\n" . chunk_split(base64_encode($spki), 64, "\n") . "-----END PUBLIC KEY-----\n";
}

function simko_asn1_len(int $len): string
{
    if ($len < 128) {
        return chr($len);
    }
    $bytes = '';
    while ($len > 0) {
        $bytes = chr($len & 0xff) . $bytes;
        $len >>= 8;
    }
    return chr(0x80 | strlen($bytes)) . $bytes;
}

function simko_asn1_int(string $bytes): string
{
    if ($bytes !== '' && (ord($bytes[0]) & 0x80)) {
        $bytes = "\x00" . $bytes;
    }
    return "\x02" . simko_asn1_len(strlen($bytes)) . $bytes;
}
