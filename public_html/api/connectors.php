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
        'ready' => $clientId !== '' && !str_contains($clientId, 'REPLACE'),
        'authorize_url' => trim((string) ($row['authorize_url'] ?? $catalog[$provider]['authorize_url'])),
    ];
}

function simko_connector_list(): array
{
    $rows = [];
    foreach (array_keys(simko_connector_catalog()) as $id) {
        $settings = simko_connector_settings($id);
        $rows[] = [
            'id' => $id,
            'name' => $settings['name'],
            'scope' => $settings['scope'],
            'ready' => $settings['ready'],
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
