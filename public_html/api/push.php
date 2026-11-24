<?php
declare(strict_types=1);

/**
 * Web Push for routine alerts. Free browser push services only (Google FCM, Mozilla, Apple, Microsoft WNS).
 * VAPID keys are self-generated and live in the private config:
 *   'push' => ['vapid_public_key' => '<base64url 65-byte P-256 point>', 'vapid_private_pem' => '-----BEGIN PRIVATE KEY-----…', 'subject' => 'mailto:noreply@simkosi.com']
 * Payloads are encrypted per RFC 8291 (aes128gcm). No library and no paid push service.
 */

require_once __DIR__ . '/bootstrap.php';

function simko_push_settings(): array
{
    $cfg = simko_config_or_empty()['push'] ?? [];
    $cfg = is_array($cfg) ? $cfg : [];
    $public = trim((string) ($cfg['vapid_public_key'] ?? ''));
    $private = (string) ($cfg['vapid_private_pem'] ?? '');
    return [
        'ready' => $public !== '' && str_contains($private, 'PRIVATE KEY'),
        'public' => $public,
        'private_pem' => $private,
        'subject' => trim((string) ($cfg['subject'] ?? 'mailto:noreply@simkosi.com')),
        // Tests only: extra push hosts (a local fake). Live keeps the built-in list.
        'extra_hosts' => array_values(array_filter((array) ($cfg['extra_hosts'] ?? []), 'is_string')),
    ];
}

function simko_push_migrate(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    $db = simko_db();
    $db->exec(
        'CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at INTEGER NOT NULL,
            last_ok INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_push_user ON push_subscriptions(user_id)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS push_prefs (
            user_id INTEGER PRIMARY KEY,
            routine_alerts INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        )'
    );
}

function simko_push_b64u(string $raw): string
{
    return rtrim(strtr(base64_encode($raw), '+/', '-_'), '=');
}

function simko_push_b64u_decode(string $text): string
{
    $text = strtr(trim($text), '-_', '+/');
    $pad = strlen($text) % 4;
    if ($pad) {
        $text .= str_repeat('=', 4 - $pad);
    }
    $out = base64_decode($text, true);
    return is_string($out) ? $out : '';
}

/** Only real browser push services, over https. */
function simko_push_endpoint_ok(string $endpoint): bool
{
    $parts = parse_url($endpoint);
    if (!is_array($parts) || empty($parts['host'])) {
        return false;
    }
    $host = strtolower((string) $parts['host']);
    $scheme = strtolower((string) ($parts['scheme'] ?? ''));
    $extra = simko_push_settings()['extra_hosts'];
    if (in_array($host . (isset($parts['port']) ? ':' . $parts['port'] : ''), $extra, true)) {
        return in_array($scheme, ['http', 'https'], true);
    }
    if ($scheme !== 'https') {
        return false;
    }
    foreach (['fcm.googleapis.com', 'updates.push.services.mozilla.com', 'push.services.mozilla.com', 'web.push.apple.com', 'push.apple.com', 'notify.windows.com'] as $allowed) {
        if ($host === $allowed || str_ends_with($host, '.' . $allowed)) {
            return true;
        }
    }
    return false;
}

function simko_push_status(int $userId): array
{
    simko_push_migrate();
    $s = simko_push_settings();
    $st = simko_db()->prepare('SELECT routine_alerts FROM push_prefs WHERE user_id = ?');
    $st->execute([$userId]);
    $n = simko_db()->prepare('SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?');
    $n->execute([$userId]);
    return [
        'available' => $s['ready'],
        'public_key' => $s['ready'] ? $s['public'] : '',
        'routine_alerts' => (int) ($st->fetchColumn() ?: 0) === 1,
        'devices' => (int) $n->fetchColumn(),
    ];
}

function simko_push_subscribe(int $userId, array $sub): array
{
    simko_push_migrate();
    if (!simko_push_settings()['ready']) {
        simko_fail(404, 'Alerts are not set up on this site yet.');
    }
    $endpoint = trim((string) ($sub['endpoint'] ?? ''));
    $keys = is_array($sub['keys'] ?? null) ? $sub['keys'] : [];
    $p256dh = trim((string) ($keys['p256dh'] ?? ''));
    $auth = trim((string) ($keys['auth'] ?? ''));
    if (strlen($endpoint) > 1000 || !simko_push_endpoint_ok($endpoint)) {
        simko_fail(400, 'That browser push service is not supported.');
    }
    $point = simko_push_b64u_decode($p256dh);
    if (strlen($point) !== 65 || $point[0] !== "\x04" || strlen(simko_push_b64u_decode($auth)) !== 16) {
        simko_fail(400, 'That browser sent an incomplete alert key.');
    }
    $db = simko_db();
    $db->prepare('DELETE FROM push_subscriptions WHERE endpoint = ?')->execute([$endpoint]);
    $db->prepare('INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent, created_at) VALUES (?, ?, ?, ?, ?, ?)')
        ->execute([$userId, $endpoint, $p256dh, $auth, substr((string) ($_SERVER['HTTP_USER_AGENT'] ?? ''), 0, 300), time()]);
    return simko_push_status($userId);
}

function simko_push_unsubscribe(int $userId, string $endpoint): array
{
    simko_push_migrate();
    simko_db()->prepare('DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?')->execute([$userId, $endpoint]);
    return simko_push_status($userId);
}

function simko_push_set_pref(int $userId, bool $on): array
{
    simko_push_migrate();
    simko_db()->prepare(
        'INSERT INTO push_prefs (user_id, routine_alerts, updated_at) VALUES (?, ?, ?)
         ON CONFLICT(user_id) DO UPDATE SET routine_alerts = excluded.routine_alerts, updated_at = excluded.updated_at'
    )->execute([$userId, $on ? 1 : 0, time()]);
    return simko_push_status($userId);
}

/* ---------- crypto ---------- */

function simko_push_point_pem(string $point): string
{
    $der = hex2bin('3059301306072a8648ce3d020106082a8648ce3d030107034200') . $point;
    return "-----BEGIN PUBLIC KEY-----\n" . chunk_split(base64_encode($der), 64, "\n") . "-----END PUBLIC KEY-----\n";
}

function simko_push_key_point($key): string
{
    $d = openssl_pkey_get_details($key);
    $x = str_pad((string) ($d['ec']['x'] ?? ''), 32, "\0", STR_PAD_LEFT);
    $y = str_pad((string) ($d['ec']['y'] ?? ''), 32, "\0", STR_PAD_LEFT);
    return "\x04" . $x . $y;
}

/** ES256 DER signature to the raw 64-byte r||s that JWT wants. */
function simko_push_der_to_raw(string $der): string
{
    $pos = 2;
    if ((ord($der[1]) & 0x80) !== 0) {
        $pos += ord($der[1]) & 0x7f;
    }
    $out = '';
    for ($i = 0; $i < 2; $i++) {
        $pos++; // 0x02
        $len = ord($der[$pos]);
        $pos++;
        $int = substr($der, $pos, $len);
        $pos += $len;
        $int = ltrim($int, "\0");
        $out .= str_pad($int, 32, "\0", STR_PAD_LEFT);
    }
    return $out;
}

function simko_push_vapid_header(string $endpoint): string
{
    $s = simko_push_settings();
    $parts = parse_url($endpoint);
    $aud = $parts['scheme'] . '://' . $parts['host'] . (isset($parts['port']) ? ':' . $parts['port'] : '');
    $input = simko_push_b64u((string) json_encode(['typ' => 'JWT', 'alg' => 'ES256']))
        . '.' . simko_push_b64u((string) json_encode(['aud' => $aud, 'exp' => time() + 12 * 3600, 'sub' => $s['subject']], JSON_UNESCAPED_SLASHES));
    $key = openssl_pkey_get_private($s['private_pem']);
    if ($key === false || !openssl_sign($input, $der, $key, OPENSSL_ALGO_SHA256)) {
        throw new RuntimeException('VAPID key could not sign.');
    }
    return 'vapid t=' . $input . '.' . simko_push_b64u(simko_push_der_to_raw($der)) . ', k=' . $s['public'];
}

/** RFC 8291 aes128gcm body for one subscription. */
function simko_push_encrypt(string $payload, string $p256dhB64u, string $authB64u): string
{
    $uaPublic = simko_push_b64u_decode($p256dhB64u);
    $authSecret = simko_push_b64u_decode($authB64u);
    $local = openssl_pkey_new(['curve_name' => 'prime256v1', 'private_key_type' => OPENSSL_KEYTYPE_EC]);
    if ($local === false) {
        throw new RuntimeException('No EC key.');
    }
    $asPublic = simko_push_key_point($local);
    $peer = openssl_pkey_get_public(simko_push_point_pem($uaPublic));
    $shared = $peer === false ? false : openssl_pkey_derive($peer, $local, 32);
    if (!is_string($shared) || strlen($shared) !== 32) {
        throw new RuntimeException('ECDH failed.');
    }
    $ikm = hash_hkdf('sha256', $shared, 32, "WebPush: info\0" . $uaPublic . $asPublic, $authSecret);
    $salt = random_bytes(16);
    $cek = hash_hkdf('sha256', $ikm, 16, "Content-Encoding: aes128gcm\0", $salt);
    $nonce = hash_hkdf('sha256', $ikm, 12, "Content-Encoding: nonce\0", $salt);
    $tag = '';
    $cipher = openssl_encrypt($payload . "\x02", 'aes-128-gcm', $cek, OPENSSL_RAW_DATA, $nonce, $tag, '', 16);
    if (!is_string($cipher)) {
        throw new RuntimeException('Encrypt failed.');
    }
    return $salt . pack('N', 4096) . chr(65) . $asPublic . $cipher . $tag;
}

/** Sends one alert to every device of the person. Returns [sent, failed]. Dead subscriptions are dropped. */
function simko_push_send_user(int $userId, array $message): array
{
    simko_push_migrate();
    if (!simko_push_settings()['ready']) {
        return [0, 0];
    }
    $st = simko_db()->prepare('SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?');
    $st->execute([$userId]);
    $payload = (string) json_encode($message + ['icon' => '/assets/icons/icon-192.png'], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    $sent = 0;
    $failed = 0;
    foreach ($st->fetchAll() as $row) {
        $endpoint = (string) $row['endpoint'];
        if (!simko_push_endpoint_ok($endpoint)) {
            continue;
        }
        try {
            $body = simko_push_encrypt($payload, (string) $row['p256dh'], (string) $row['auth']);
            $ch = curl_init($endpoint);
            curl_setopt_array($ch, [
                CURLOPT_POST => true,
                CURLOPT_POSTFIELDS => $body,
                CURLOPT_HTTPHEADER => [
                    'Authorization: ' . simko_push_vapid_header($endpoint),
                    'Content-Encoding: aes128gcm',
                    'Content-Type: application/octet-stream',
                    'TTL: 86400',
                    'Urgency: normal',
                ],
                CURLOPT_RETURNTRANSFER => true,
                CURLOPT_TIMEOUT => 15,
            ]);
            curl_exec($ch);
            $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
            curl_close($ch);
        } catch (Throwable $e) {
            $code = 0;
        }
        if ($code >= 200 && $code < 300) {
            $sent++;
            simko_db()->prepare('UPDATE push_subscriptions SET last_ok = ?, failures = 0 WHERE id = ?')->execute([time(), (int) $row['id']]);
        } else {
            $failed++;
            if ($code === 404 || $code === 410) {
                simko_db()->prepare('DELETE FROM push_subscriptions WHERE id = ?')->execute([(int) $row['id']]);
            } else {
                simko_db()->prepare('UPDATE push_subscriptions SET failures = failures + 1 WHERE id = ?')->execute([(int) $row['id']]);
            }
        }
    }
    return [$sent, $failed];
}

function simko_push_test(int $userId): array
{
    $status = simko_push_status($userId);
    if (!$status['available']) {
        simko_fail(404, 'Alerts are not set up on this site yet.');
    }
    if ($status['devices'] < 1) {
        simko_fail(400, 'Turn on alerts on this device first.');
    }
    simko_throttle_check('pushtest:' . $userId, 10, 3600);
    simko_throttle_hit('pushtest:' . $userId);
    [$sent, $failed] = simko_push_send_user($userId, [
        'title' => 'Simko SI',
        'body' => 'Test alert: alerts work on this device.',
        'tag' => 'simko-test',
        'url' => '/',
    ]);
    return ['sent' => $sent, 'failed' => $failed] + simko_push_status($userId);
}

/** Called by the routines worker after a routine is delivered. Never throws. */
function simko_push_routine(int $userId, string $body): void
{
    try {
        if (!simko_push_status($userId)['routine_alerts']) {
            return;
        }
        simko_push_send_user($userId, ['title' => 'Simko SI routine', 'body' => $body, 'tag' => 'simko-routine', 'url' => '/']);
    } catch (Throwable $e) {
        // The in-app note still stands if push is down.
    }
}
