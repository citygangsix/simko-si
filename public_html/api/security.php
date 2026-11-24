<?php
declare(strict_types=1);

/**
 * Two-step sign-in (TOTP, RFC 6238) with 8 one-time backup codes, and the signed-in devices list.
 * Opt-in per account. Tables are additive (CREATE TABLE IF NOT EXISTS / ADD COLUMN only).
 * The TOTP secret is sealed with libsodium; the key comes from connectors.token_key in the private
 * config, or from data/security.key (made once, 0600) when that is not set.
 */

require_once __DIR__ . '/bootstrap.php';

const SIMKO_TOTP_STEP = 30;
const SIMKO_TOTP_DIGITS = 6;
const SIMKO_BACKUP_CODES = 8;
const SIMKO_TWOFA_CHALLENGE_TTL = 600;

function simko_security_migrate(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    $db = simko_db();
    $db->exec(
        'CREATE TABLE IF NOT EXISTS user_totp (
            user_id INTEGER PRIMARY KEY,
            secret_nonce BLOB,
            secret_cipher BLOB,
            pending_nonce BLOB,
            pending_cipher BLOB,
            pending_at INTEGER NOT NULL DEFAULT 0,
            enabled_at INTEGER NOT NULL DEFAULT 0,
            last_step INTEGER NOT NULL DEFAULT 0
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS user_backup_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            used_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_backup_codes_user ON user_backup_codes(user_id)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS twofa_challenges (
            challenge_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0
        )'
    );
    simko_security_add_token_columns($db);
}

/** auth_tokens gets device columns. Add-only, checked first, so it is safe to run on every request. */
function simko_security_add_token_columns(PDO $db): void
{
    $have = [];
    foreach ($db->query('PRAGMA table_info(auth_tokens)')->fetchAll() as $col) {
        $have[(string) $col['name']] = true;
    }
    $want = [
        'created_at' => 'INTEGER NOT NULL DEFAULT 0',
        'last_seen' => 'INTEGER NOT NULL DEFAULT 0',
        'user_agent' => 'TEXT',
        'ip_masked' => 'TEXT',
    ];
    foreach ($want as $name => $def) {
        if (!isset($have[$name])) {
            try {
                $db->exec('ALTER TABLE auth_tokens ADD COLUMN ' . $name . ' ' . $def);
            } catch (Throwable $e) {
                // Another request added it first.
            }
        }
    }
}

/* ---------- small crypto helpers ---------- */

function simko_security_key(): string
{
    $raw = (string) ((simko_config_or_empty()['connectors']['token_key'] ?? ''));
    if (strlen($raw) < 16 || str_contains($raw, 'REPLACE')) {
        $file = simko_private_dir() . '/data/security.key';
        $raw = is_file($file) ? (string) file_get_contents($file) : '';
        if (strlen($raw) < 32) {
            $raw = bin2hex(random_bytes(32));
            $old = umask(077);
            @file_put_contents($file, $raw, LOCK_EX);
            umask($old);
            @chmod($file, 0600);
        }
    }
    return sodium_crypto_generichash('simko-totp|' . $raw, '', SODIUM_CRYPTO_SECRETBOX_KEYBYTES);
}

function simko_security_seal(string $plain): array
{
    $nonce = random_bytes(SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
    return [$nonce, sodium_crypto_secretbox($plain, $nonce, simko_security_key())];
}

function simko_security_open(?string $cipher, ?string $nonce): string
{
    if (!is_string($cipher) || !is_string($nonce) || $cipher === '' || $nonce === '') {
        return '';
    }
    $plain = sodium_crypto_secretbox_open($cipher, $nonce, simko_security_key());
    return is_string($plain) ? $plain : '';
}

function simko_base32_encode(string $bytes): string
{
    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    $bits = '';
    foreach (str_split($bytes) as $c) {
        $bits .= str_pad(decbin(ord($c)), 8, '0', STR_PAD_LEFT);
    }
    $out = '';
    foreach (str_split($bits, 5) as $chunk) {
        $out .= $alphabet[bindec(str_pad($chunk, 5, '0', STR_PAD_RIGHT))];
    }
    return $out;
}

function simko_base32_decode(string $text): string
{
    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    $text = strtoupper(preg_replace('/[^A-Za-z2-7]/', '', $text) ?? '');
    $bits = '';
    foreach (str_split($text) as $c) {
        $pos = strpos($alphabet, $c);
        if ($pos === false) {
            return '';
        }
        $bits .= str_pad(decbin($pos), 5, '0', STR_PAD_LEFT);
    }
    $out = '';
    foreach (str_split($bits, 8) as $byte) {
        if (strlen($byte) === 8) {
            $out .= chr(bindec($byte));
        }
    }
    return $out;
}

function simko_totp_code(string $secretBytes, int $step): string
{
    $msg = pack('N2', ($step >> 32) & 0xffffffff, $step & 0xffffffff);
    $hash = hash_hmac('sha1', $msg, $secretBytes, true);
    $off = ord($hash[19]) & 0x0f;
    $num = ((ord($hash[$off]) & 0x7f) << 24) | (ord($hash[$off + 1]) << 16) | (ord($hash[$off + 2]) << 8) | ord($hash[$off + 3]);
    return str_pad((string) ($num % (10 ** SIMKO_TOTP_DIGITS)), SIMKO_TOTP_DIGITS, '0', STR_PAD_LEFT);
}

/** Returns the matching time step (one step of clock drift allowed either way), or 0. */
function simko_totp_match(string $secretB32, string $code, int $notBefore = 0): int
{
    $code = preg_replace('/\D/', '', $code) ?? '';
    if (strlen($code) !== SIMKO_TOTP_DIGITS) {
        return 0;
    }
    $bytes = simko_base32_decode($secretB32);
    if ($bytes === '') {
        return 0;
    }
    $now = intdiv(time(), SIMKO_TOTP_STEP);
    foreach ([0, -1, 1] as $d) {
        $step = $now + $d;
        if ($step <= $notBefore) {
            continue;
        }
        if (hash_equals(simko_totp_code($bytes, $step), $code)) {
            return $step;
        }
    }
    return 0;
}

function simko_backup_normalize(string $code): string
{
    return strtolower(preg_replace('/[^A-Za-z0-9]/', '', $code) ?? '');
}

function simko_backup_hash(int $userId, string $code): string
{
    return hash_hmac('sha256', $userId . ':' . simko_backup_normalize($code), simko_security_key());
}

/* ---------- 2FA state ---------- */

function simko_twofa_row(int $userId): ?array
{
    simko_security_migrate();
    $st = simko_db()->prepare('SELECT * FROM user_totp WHERE user_id = ?');
    $st->execute([$userId]);
    $row = $st->fetch();
    return $row ?: null;
}

function simko_twofa_enabled(int $userId): bool
{
    $row = simko_twofa_row($userId);
    return $row !== null && (int) $row['enabled_at'] > 0;
}

function simko_twofa_status(int $userId): array
{
    $row = simko_twofa_row($userId);
    $st = simko_db()->prepare('SELECT COUNT(*) FROM user_backup_codes WHERE user_id = ? AND used_at = 0');
    $st->execute([$userId]);
    return [
        'enabled' => $row !== null && (int) $row['enabled_at'] > 0,
        'enabled_at' => $row ? (int) $row['enabled_at'] : 0,
        'backup_codes_left' => (int) $st->fetchColumn(),
    ];
}

function simko_twofa_setup(array $user): array
{
    $uid = (int) $user['id'];
    if (simko_twofa_enabled($uid)) {
        simko_fail(409, 'Two-step sign-in is already on.');
    }
    $secret = simko_base32_encode(random_bytes(20));
    [$nonce, $cipher] = simko_security_seal($secret);
    $db = simko_db();
    $db->prepare('INSERT OR IGNORE INTO user_totp (user_id) VALUES (?)')->execute([$uid]);
    $db->prepare('UPDATE user_totp SET pending_nonce = ?, pending_cipher = ?, pending_at = ? WHERE user_id = ?')
        ->execute([$nonce, $cipher, time(), $uid]);
    $label = rawurlencode('Simko SI:' . (string) $user['email']);
    $uri = 'otpauth://totp/' . $label . '?secret=' . $secret . '&issuer=' . rawurlencode('Simko SI')
        . '&algorithm=SHA1&digits=' . SIMKO_TOTP_DIGITS . '&period=' . SIMKO_TOTP_STEP;
    return ['secret' => $secret, 'otpauth' => $uri];
}

function simko_twofa_new_backup_codes(int $userId): array
{
    $db = simko_db();
    $db->prepare('DELETE FROM user_backup_codes WHERE user_id = ?')->execute([$userId]);
    $codes = [];
    $alphabet = 'abcdefghjkmnpqrstuvwxyz23456789';
    $ins = $db->prepare('INSERT INTO user_backup_codes (user_id, code_hash, used_at, created_at) VALUES (?, ?, 0, ?)');
    for ($i = 0; $i < SIMKO_BACKUP_CODES; $i++) {
        $raw = '';
        for ($j = 0; $j < 10; $j++) {
            $raw .= $alphabet[random_int(0, strlen($alphabet) - 1)];
        }
        $code = substr($raw, 0, 5) . '-' . substr($raw, 5);
        $codes[] = $code;
        $ins->execute([$userId, simko_backup_hash($userId, $code), time()]);
    }
    return $codes;
}

function simko_twofa_enable(array $user, string $code): array
{
    $uid = (int) $user['id'];
    $row = simko_twofa_row($uid);
    if ($row !== null && (int) $row['enabled_at'] > 0) {
        simko_fail(409, 'Two-step sign-in is already on.');
    }
    $limits = simko_throttle_settings();
    $bucket = 'tfaset:' . $uid;
    simko_throttle_check($bucket, $limits['account'], $limits['window']);
    $secret = $row ? simko_security_open($row['pending_cipher'] ?? null, $row['pending_nonce'] ?? null) : '';
    if ($secret === '' || (int) ($row['pending_at'] ?? 0) < time() - 3600) {
        simko_fail(400, 'Start again: tap Turn on two-step sign-in.');
    }
    $step = simko_totp_match($secret, $code);
    if ($step === 0) {
        simko_throttle_hit($bucket);
        simko_fail(400, 'That code did not match. Check the time on your phone and try the newest code.');
    }
    simko_throttle_clear($bucket);
    [$nonce, $cipher] = simko_security_seal($secret);
    simko_db()->prepare(
        'UPDATE user_totp SET secret_nonce = ?, secret_cipher = ?, pending_nonce = NULL, pending_cipher = NULL,
         pending_at = 0, enabled_at = ?, last_step = ? WHERE user_id = ?'
    )->execute([$nonce, $cipher, time(), $step, $uid]);
    $codes = simko_twofa_new_backup_codes($uid);
    simko_security_audit($uid, 'twofa_on');
    return ['backup_codes' => $codes] + simko_twofa_status($uid);
}

/**
 * Checks a 6-digit app code or an unused backup code for a user whose two-step sign-in is on.
 * Returns 'totp', 'backup' or '' (no match). App codes cannot be replayed; backup codes work once.
 */
function simko_twofa_check(int $userId, string $code): string
{
    $row = simko_twofa_row($userId);
    if ($row === null || (int) $row['enabled_at'] === 0) {
        return '';
    }
    $digits = preg_replace('/\D/', '', $code) ?? '';
    if (strlen($digits) === SIMKO_TOTP_DIGITS && strlen(simko_backup_normalize($code)) === SIMKO_TOTP_DIGITS) {
        $secret = simko_security_open($row['secret_cipher'] ?? null, $row['secret_nonce'] ?? null);
        $step = simko_totp_match($secret, $digits, (int) $row['last_step']);
        if ($step > 0) {
            $upd = simko_db()->prepare('UPDATE user_totp SET last_step = ? WHERE user_id = ? AND last_step < ?');
            $upd->execute([$step, $userId, $step]);
            return $upd->rowCount() > 0 ? 'totp' : '';
        }
        return '';
    }
    if (strlen(simko_backup_normalize($code)) !== 10) {
        return '';
    }
    $use = simko_db()->prepare('UPDATE user_backup_codes SET used_at = ? WHERE user_id = ? AND code_hash = ? AND used_at = 0');
    $use->execute([time(), $userId, simko_backup_hash($userId, $code)]);
    return $use->rowCount() > 0 ? 'backup' : '';
}

function simko_twofa_disable(array $user, string $password, string $code): array
{
    $uid = (int) $user['id'];
    if (!simko_twofa_enabled($uid)) {
        simko_fail(409, 'Two-step sign-in is already off.');
    }
    $limits = simko_throttle_settings();
    $bucket = 'tfaoff:' . $uid;
    simko_throttle_check($bucket, $limits['account'], $limits['window']);
    $st = simko_db()->prepare('SELECT password_hash FROM users WHERE id = ?');
    $st->execute([$uid]);
    $hash = (string) $st->fetchColumn();
    if ($password === '' || !password_verify($password, $hash) || simko_twofa_check($uid, $code) === '') {
        simko_throttle_hit($bucket);
        simko_fail(401, 'The password or code did not match.');
    }
    simko_throttle_clear($bucket);
    simko_db()->prepare('DELETE FROM user_totp WHERE user_id = ?')->execute([$uid]);
    simko_db()->prepare('DELETE FROM user_backup_codes WHERE user_id = ?')->execute([$uid]);
    simko_security_audit($uid, 'twofa_off');
    return simko_twofa_status($uid);
}

/** Password was right and two-step is on: hand back a short-lived challenge instead of a session. */
function simko_twofa_challenge(int $userId): string
{
    simko_security_migrate();
    $challenge = bin2hex(random_bytes(24));
    $db = simko_db();
    $db->prepare('DELETE FROM twofa_challenges WHERE expires_at < ?')->execute([time()]);
    $db->prepare('INSERT INTO twofa_challenges (challenge_hash, user_id, created_at, expires_at, attempts) VALUES (?, ?, ?, ?, 0)')
        ->execute([hash('sha256', $challenge), $userId, time(), time() + SIMKO_TWOFA_CHALLENGE_TTL]);
    return $challenge;
}

/**
 * The code step of sign-in. Throttled per network and per account (the same limits as passwords),
 * and each challenge allows 5 tries. Returns the user id on success.
 */
function simko_twofa_verify_challenge(string $challenge, string $code): int
{
    simko_security_migrate();
    $limits = simko_throttle_settings();
    $ipBucket = 'tfaip:' . simko_client_net();
    simko_throttle_check($ipBucket, $limits['ip'], $limits['window']);
    $db = simko_db();
    $st = $db->prepare('SELECT user_id, expires_at, attempts FROM twofa_challenges WHERE challenge_hash = ?');
    $st->execute([hash('sha256', $challenge)]);
    $row = $st->fetch();
    if (!$row || (int) $row['expires_at'] < time() || (int) $row['attempts'] >= 5) {
        simko_throttle_hit($ipBucket);
        simko_fail(401, 'That sign-in step expired. Sign in again with your password.', ['twofa_restart' => true]);
    }
    $uid = (int) $row['user_id'];
    $acctBucket = 'tfacct:' . $uid;
    simko_throttle_check($acctBucket, $limits['account'], $limits['window']);
    $kind = simko_twofa_check($uid, $code);
    if ($kind === '') {
        $db->prepare('UPDATE twofa_challenges SET attempts = attempts + 1 WHERE challenge_hash = ?')->execute([hash('sha256', $challenge)]);
        simko_throttle_hit($ipBucket);
        simko_throttle_hit($acctBucket);
        simko_fail(401, 'That code did not match. Use the newest 6-digit code from your app, or a backup code.');
    }
    simko_throttle_clear($acctBucket);
    $db->prepare('DELETE FROM twofa_challenges WHERE challenge_hash = ?')->execute([hash('sha256', $challenge)]);
    if ($kind === 'backup') {
        simko_security_audit($uid, 'twofa_backup_used');
    }
    return $uid;
}

/* ---------- devices ---------- */

function simko_mask_ip(string $ip): string
{
    if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
        $p = explode('.', $ip);
        return $p[0] . '.' . $p[1] . '.x.x';
    }
    if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6)) {
        $bin = inet_pton($ip);
        if ($bin !== false) {
            $parts = str_split(bin2hex(substr($bin, 0, 4)), 4);
            return $parts[0] . ':' . $parts[1] . ':x:x::';
        }
    }
    return 'unknown';
}

/** Browser and OS in plain words from a User-Agent string. */
function simko_describe_agent(string $ua): array
{
    $browser = 'Browser';
    if ($ua === '') {
        $browser = 'Unknown browser';
    } elseif (str_contains($ua, 'SimkoSI') || str_contains($ua, '; wv)')) {
        $browser = 'Simko SI app';
    } elseif (preg_match('/Edg(A|iOS)?\//', $ua)) {
        $browser = 'Edge';
    } elseif (preg_match('/OPR\/|Opera/', $ua)) {
        $browser = 'Opera';
    } elseif (preg_match('/SamsungBrowser\//', $ua)) {
        $browser = 'Samsung Internet';
    } elseif (preg_match('/Firefox\/|FxiOS\//', $ua)) {
        $browser = 'Firefox';
    } elseif (preg_match('/Chrome\/|CriOS\//', $ua)) {
        $browser = 'Chrome';
    } elseif (preg_match('/Safari\//', $ua)) {
        $browser = 'Safari';
    } elseif (preg_match('/curl|python|node|Go-http|okhttp/i', $ua)) {
        $browser = 'Script or app';
    }
    $os = 'Unknown OS';
    if (preg_match('/iPhone|iPod/', $ua)) {
        $os = 'iPhone';
    } elseif (str_contains($ua, 'iPad')) {
        $os = 'iPad';
    } elseif (str_contains($ua, 'Android')) {
        $os = 'Android';
    } elseif (str_contains($ua, 'Windows')) {
        $os = 'Windows';
    } elseif (str_contains($ua, 'CrOS')) {
        $os = 'ChromeOS';
    } elseif (str_contains($ua, 'Mac OS X') || str_contains($ua, 'Macintosh')) {
        $os = 'Mac';
    } elseif (str_contains($ua, 'Linux')) {
        $os = 'Linux';
    }
    return ['browser' => $browser, 'os' => $os];
}

/** Called right after a session token is stored: note the device it belongs to. */
function simko_security_note_token(string $token): void
{
    simko_security_migrate();
    $ua = substr((string) ($_SERVER['HTTP_USER_AGENT'] ?? ''), 0, 400);
    simko_db()->prepare('UPDATE auth_tokens SET created_at = ?, last_seen = ?, user_agent = ?, ip_masked = ? WHERE token_hash = ?')
        ->execute([time(), time(), $ua, simko_mask_ip((string) ($_SERVER['REMOTE_ADDR'] ?? '')), hash('sha256', $token)]);
}

/** Last-seen is written at most once a minute per session. */
function simko_security_touch(string $token): void
{
    try {
        simko_security_migrate();
        simko_db()->prepare('UPDATE auth_tokens SET last_seen = ?, ip_masked = COALESCE(ip_masked, ?) WHERE token_hash = ? AND last_seen < ?')
            ->execute([time(), simko_mask_ip((string) ($_SERVER['REMOTE_ADDR'] ?? '')), hash('sha256', $token), time() - 60]);
    } catch (Throwable $e) {
        // Never block a request on the device note.
    }
}

function simko_current_token_hash(int $userId): string
{
    foreach (simko_token_candidates() as $token) {
        $st = simko_db()->prepare('SELECT token_hash FROM auth_tokens WHERE token_hash = ? AND user_id = ? AND expires_at > ?');
        $st->execute([hash('sha256', $token), $userId, time()]);
        $h = $st->fetchColumn();
        if (is_string($h) && $h !== '') {
            return $h;
        }
    }
    return '';
}

function simko_devices(int $userId): array
{
    simko_security_migrate();
    $current = simko_current_token_hash($userId);
    $st = simko_db()->prepare(
        'SELECT rowid AS id, token_hash, created_at, last_seen, user_agent, ip_masked FROM auth_tokens
         WHERE user_id = ? AND expires_at > ? ORDER BY (token_hash = ?) DESC, last_seen DESC, rowid DESC'
    );
    $st->execute([$userId, time(), $current]);
    $out = [];
    foreach ($st->fetchAll() as $row) {
        $agent = simko_describe_agent((string) ($row['user_agent'] ?? ''));
        $out[] = [
            'id' => (int) $row['id'],
            'browser' => $agent['browser'],
            'os' => $agent['os'],
            'ip' => (string) ($row['ip_masked'] ?? '') !== '' ? (string) $row['ip_masked'] : 'unknown',
            'created_at' => (int) $row['created_at'],
            'last_seen' => (int) $row['last_seen'],
            'current' => $current !== '' && hash_equals($current, (string) $row['token_hash']),
        ];
    }
    return $out;
}

function simko_device_signout(int $userId, int $deviceId): array
{
    simko_security_migrate();
    $current = simko_current_token_hash($userId);
    $st = simko_db()->prepare('SELECT token_hash FROM auth_tokens WHERE rowid = ? AND user_id = ?');
    $st->execute([$deviceId, $userId]);
    $hash = $st->fetchColumn();
    if (!is_string($hash) || $hash === '') {
        simko_fail(404, 'That device is not signed in.');
    }
    if ($current !== '' && hash_equals($current, $hash)) {
        simko_fail(400, 'This is the device you are using. Use Sign out instead.');
    }
    simko_db()->prepare('DELETE FROM auth_tokens WHERE rowid = ? AND user_id = ?')->execute([$deviceId, $userId]);
    simko_security_audit($userId, 'device_signout');
    return simko_devices($userId);
}

function simko_devices_signout_others(int $userId): array
{
    simko_security_migrate();
    $current = simko_current_token_hash($userId);
    if ($current === '') {
        simko_fail(401, 'Sign in again first.');
    }
    $st = simko_db()->prepare('DELETE FROM auth_tokens WHERE user_id = ? AND token_hash <> ?');
    $st->execute([$userId, $current]);
    simko_security_audit($userId, 'devices_signout_others');
    return ['devices' => simko_devices($userId), 'signed_out' => $st->rowCount()];
}

function simko_security_audit(int $userId, string $action): void
{
    try {
        $cols = [];
        foreach (simko_db()->query('PRAGMA table_info(audit_log)')->fetchAll() as $c) {
            $cols[] = (string) $c['name'];
        }
        $summaries = [
            'twofa_on' => 'Two-step sign-in turned on',
            'twofa_off' => 'Two-step sign-in turned off',
            'twofa_backup_used' => 'A backup code was used to sign in',
            'device_signout' => 'Signed out one device',
            'devices_signout_others' => 'Signed out all other devices',
        ];
        if (in_array('user_id', $cols, true) && in_array('action', $cols, true) && in_array('summary', $cols, true)) {
            simko_db()->prepare('INSERT INTO audit_log (user_id, action, summary, created_at) VALUES (?, ?, ?, ?)')
                ->execute([$userId, $action, $summaries[$action] ?? $action, time()]);
        }
    } catch (Throwable $e) {
        // The audit row is a nice-to-have.
    }
}
