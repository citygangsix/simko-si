<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_oauth_config(string $provider): array
{
    $all = simko_config_or_empty()['oauth'] ?? [];
    $row = is_array($all) && isset($all[$provider]) && is_array($all[$provider]) ? $all[$provider] : [];
    return [
        'client_id' => trim((string) ($row['client_id'] ?? '')),
        'client_secret' => (string) ($row['client_secret'] ?? ''),
        'authorize_url' => trim((string) ($row['authorize_url'] ?? '')),
        'token_url' => trim((string) ($row['token_url'] ?? '')),
        'userinfo_url' => trim((string) ($row['userinfo_url'] ?? '')),
        'redirect_url' => trim((string) ($row['redirect_url'] ?? '')),
        'scope' => trim((string) ($row['scope'] ?? 'openid email')),
    ];
}

function simko_oauth_ready(string $provider): bool
{
    if (!simko_flag('oauth')) {
        return false;
    }
    $cfg = simko_oauth_config($provider);
    return $cfg['client_id'] !== '' && !str_contains($cfg['client_id'], 'REPLACE');
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
    $stmt = simko_db()->prepare('INSERT INTO oauth_states (state, provider, created_at) VALUES (?, ?, ?)');
    $stmt->execute([$state, $provider, time()]);
    $redirect = $cfg['redirect_url'] !== '' ? $cfg['redirect_url'] : rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/') . '/api/oauth/callback';
    $query = http_build_query([
        'client_id' => $cfg['client_id'],
        'redirect_uri' => $redirect,
        'response_type' => 'code',
        'scope' => $cfg['scope'],
        'state' => $state,
    ]);
    return ['url' => $cfg['authorize_url'] . (str_contains($cfg['authorize_url'], '?') ? '&' : '?') . $query, 'state' => $state];
}

function simko_oauth_finish(string $provider, string $code, string $state): array
{
    if (!simko_oauth_ready($provider) || $code === '' || $state === '') {
        simko_fail(400, 'That sign-in could not be finished.');
    }
    $stmt = simko_db()->prepare('SELECT provider, created_at FROM oauth_states WHERE state = ?');
    $stmt->execute([$state]);
    $saved = $stmt->fetch();
    simko_db()->prepare('DELETE FROM oauth_states WHERE state = ?')->execute([$state]);
    if (!$saved || (string) $saved['provider'] !== $provider || (int) $saved['created_at'] < time() - 600) {
        simko_fail(400, 'That sign-in expired. Try again.');
    }
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
        $save = simko_db()->prepare('INSERT INTO oauth_identities (provider, subject, user_id, created_at) VALUES (?, ?, ?, ?)');
        $save->execute([$provider, $sub, $userId, time()]);
    }
    $issued = simko_issue_token($userId);
    $emailStmt = simko_db()->prepare('SELECT email FROM users WHERE id = ?');
    $emailStmt->execute([$userId]);
    return ['token' => $issued, 'email' => (string) $emailStmt->fetchColumn()];
}
