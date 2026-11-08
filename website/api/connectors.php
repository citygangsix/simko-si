<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_connector_catalog(): array
{
    return [
        'google-drive' => [
            'name' => 'Google Drive',
            'scope' => 'https://www.googleapis.com/auth/drive.readonly',
            'authorize_url' => 'https://accounts.google.com/o/oauth2/v2/auth',
        ],
        'github' => [
            'name' => 'GitHub',
            'scope' => 'read:user public_repo',
            'authorize_url' => 'https://github.com/login/oauth/authorize',
        ],
    ];
}

function simko_connector_settings(string $provider): array
{
    $catalog = simko_connector_catalog();
    if (!isset($catalog[$provider])) {
        simko_fail(400, 'That connector is not offered. Gmail and banking are not connected.');
    }
    $all = simko_config_or_empty()['connectors'] ?? [];
    $row = is_array($all) && isset($all[$provider]) && is_array($all[$provider]) ? $all[$provider] : [];
    $clientId = trim((string) ($row['client_id'] ?? ''));
    return $catalog[$provider] + [
        'client_id' => $clientId,
        'client_secret' => (string) ($row['client_secret'] ?? ''),
        'token_url' => trim((string) ($row['token_url'] ?? '')),
        'revoke_url' => trim((string) ($row['revoke_url'] ?? '')),
        'ready' => $clientId !== '' && !str_contains($clientId, 'REPLACE'),
        'authorize_url' => trim((string) ($row['authorize_url'] ?? $catalog[$provider]['authorize_url'])),
    ];
}

function simko_connector_list(int $userId = 0): array
{
    $grants = [];
    if ($userId > 0) {
        $stmt = simko_db()->prepare('SELECT provider, expires_at, scope FROM connector_grants WHERE user_id = ?');
        $stmt->execute([$userId]);
        foreach ($stmt->fetchAll() as $row) {
            $grants[(string) $row['provider']] = $row;
        }
    }
    $rows = [];
    foreach (array_keys(simko_connector_catalog()) as $id) {
        $settings = simko_connector_settings($id);
        $grant = $grants[$id] ?? null;
        $rows[] = [
            'id' => $id,
            'name' => $settings['name'],
            'scope' => $settings['scope'],
            'ready' => $settings['ready'],
            'connected' => $grant !== null,
            'expires_at' => $grant ? (int) $grant['expires_at'] : 0,
        ];
    }
    return $rows;
}

function simko_connector_start(int $userId, string $provider): array
{
    $settings = simko_connector_settings($provider);
    if (!$settings['ready']) {
        simko_fail(404, $settings['name'] . ' stays hidden until its client id is set.');
    }
    $state = bin2hex(random_bytes(16));
    $stmt = simko_db()->prepare(
        'INSERT INTO connector_states (state, user_id, provider, created_at) VALUES (?, ?, ?, ?)'
    );
    $stmt->execute([$state, $userId, $provider, time()]);
    $query = http_build_query([
        'client_id' => $settings['client_id'],
        'redirect_uri' => rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/') . '/api/connector/callback',
        'response_type' => 'code',
        'scope' => $settings['scope'],
        'state' => $state,
    ]);
    return ['url' => $settings['authorize_url'] . '?' . $query, 'scope' => $settings['scope']];
}

function simko_connector_key(): string
{
    $raw = (string) ((simko_config_or_empty()['connectors']['token_key'] ?? ''));
    if (strlen($raw) < 16 || str_contains($raw, 'REPLACE')) {
        simko_fail(500, 'Connector token storage is not configured.');
    }
    return sodium_crypto_generichash($raw, '', SODIUM_CRYPTO_SECRETBOX_KEYBYTES);
}

function simko_connector_seal(string $plain, string $key): array
{
    $nonce = random_bytes(SODIUM_CRYPTO_SECRETBOX_NONCEBYTES);
    return [$nonce, sodium_crypto_secretbox($plain, $nonce, $key)];
}

function simko_connector_open(string $cipher, string $nonce, string $key): string
{
    $plain = sodium_crypto_secretbox_open($cipher, $nonce, $key);
    if (!is_string($plain)) {
        simko_fail(500, 'The saved connector could not be opened.');
    }
    return $plain;
}

function simko_connector_exchange(int $userId, string $provider, string $code, string $state): void
{
    $stmt = simko_db()->prepare('SELECT user_id, provider, created_at FROM connector_states WHERE state = ?');
    $stmt->execute([$state]);
    $saved = $stmt->fetch();
    simko_db()->prepare('DELETE FROM connector_states WHERE state = ?')->execute([$state]);
    if (!$saved || (int) $saved['user_id'] !== $userId || (string) $saved['provider'] !== $provider || (int) $saved['created_at'] < time() - 600) {
        simko_fail(400, 'That connection expired. Try again.');
    }
    $settings = simko_connector_settings($provider);
    if ($settings['token_url'] === '' || $settings['client_secret'] === '') {
        simko_fail(500, 'That connector is not configured.');
    }
    $redirect = rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/') . '/api/connector/callback';
    $body = http_build_query([
        'code' => $code,
        'client_id' => $settings['client_id'],
        'client_secret' => $settings['client_secret'],
        'redirect_uri' => $redirect,
        'grant_type' => 'authorization_code',
    ]);
    $token = simko_connector_token_request($settings['token_url'], $body);
    simko_connector_store($userId, $provider, $token, $settings['scope']);
}

function simko_connector_token_request(string $url, string $body): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $body,
        CURLOPT_HTTPHEADER => ['Content-Type: application/x-www-form-urlencoded', 'Accept: application/json'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
    ]);
    $raw = curl_exec($ch);
    curl_close($ch);
    $data = is_string($raw) ? json_decode($raw, true) : null;
    if (!is_array($data) || empty($data['access_token'])) {
        simko_fail(401, 'That connection was not accepted.');
    }
    return $data;
}

function simko_connector_store(int $userId, string $provider, array $token, string $scope): void
{
    $key = simko_connector_key();
    [$accessNonce, $accessCipher] = simko_connector_seal((string) $token['access_token'], $key);
    $refresh = (string) ($token['refresh_token'] ?? '');
    $refreshNonce = null;
    $refreshCipher = null;
    if ($refresh !== '') {
        [$refreshNonce, $refreshCipher] = simko_connector_seal($refresh, $key);
    }
    sodium_memzero($key);
    $expires = time() + (int) ($token['expires_in'] ?? 3600);
    simko_db()->prepare(
        'INSERT INTO connector_grants (user_id, provider, access_nonce, access_cipher, refresh_nonce, refresh_cipher, expires_at, scope, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(user_id, provider) DO UPDATE SET
            access_nonce = excluded.access_nonce,
            access_cipher = excluded.access_cipher,
            refresh_nonce = COALESCE(excluded.refresh_nonce, connector_grants.refresh_nonce),
            refresh_cipher = COALESCE(excluded.refresh_cipher, connector_grants.refresh_cipher),
            expires_at = excluded.expires_at,
            scope = excluded.scope,
            updated_at = excluded.updated_at'
    )->execute([$userId, $provider, $accessNonce, $accessCipher, $refreshNonce, $refreshCipher, $expires, $scope, time()]);
}

function simko_connector_refresh(int $userId, string $provider): array
{
    $settings = simko_connector_settings($provider);
    $stmt = simko_db()->prepare('SELECT refresh_nonce, refresh_cipher, scope FROM connector_grants WHERE user_id = ? AND provider = ?');
    $stmt->execute([$userId, $provider]);
    $row = $stmt->fetch();
    if (!$row || $row['refresh_cipher'] === null || $settings['token_url'] === '') {
        simko_fail(404, 'That connector is not connected.');
    }
    $key = simko_connector_key();
    $refresh = simko_connector_open((string) $row['refresh_cipher'], (string) $row['refresh_nonce'], $key);
    sodium_memzero($key);
    $body = http_build_query([
        'client_id' => $settings['client_id'],
        'client_secret' => $settings['client_secret'],
        'refresh_token' => $refresh,
        'grant_type' => 'refresh_token',
    ]);
    $token = simko_connector_token_request($settings['token_url'], $body);
    if (empty($token['refresh_token'])) {
        $token['refresh_token'] = $refresh;
    }
    simko_connector_store($userId, $provider, $token, (string) $row['scope']);
    return ['connected' => true, 'provider' => $provider];
}

function simko_connector_disconnect(int $userId, string $provider): void
{
    $settings = simko_connector_settings($provider);
    $stmt = simko_db()->prepare('SELECT access_nonce, access_cipher FROM connector_grants WHERE user_id = ? AND provider = ?');
    $stmt->execute([$userId, $provider]);
    $row = $stmt->fetch();
    if (!$row) {
        simko_fail(404, 'That connector is not on this account.');
    }
    if ($settings['revoke_url'] !== '') {
        $key = simko_connector_key();
        $access = simko_connector_open((string) $row['access_cipher'], (string) $row['access_nonce'], $key);
        sodium_memzero($key);
        $ch = curl_init($settings['revoke_url']);
        curl_setopt_array($ch, [
            CURLOPT_POST => true,
            CURLOPT_POSTFIELDS => http_build_query(['token' => $access]),
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_TIMEOUT => 15,
        ]);
        curl_exec($ch);
        curl_close($ch);
    }
    simko_db()->prepare('DELETE FROM connector_grants WHERE user_id = ? AND provider = ?')->execute([$userId, $provider]);
}
