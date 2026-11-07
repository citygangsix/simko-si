<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$tokenPort = 9083;
$sitePort = 9082;
$log = sys_get_temp_dir() . '/simko-connector-log-' . getmypid() . '.txt';
$cmd = 'php -S 127.0.0.1:' . $tokenPort . ' ' . escapeshellarg(dirname(__DIR__) . '/tests/fake-connector.php');
$env = getenv();
if (!is_array($env)) {
    $env = [];
}
$env['SIMKO_CONNECTOR_LOG'] = $log;
$fake = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $fakePipes, dirname(__DIR__), $env);
$private = platform_private('connector-save', ['connectors' => true], [
    'connectors' => [
        'token_key' => 'test-only-connector-key',
        'google-drive' => [
            'client_id' => 'drive-client',
            'client_secret' => 'drive-secret',
            'authorize_url' => 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url' => 'http://127.0.0.1:' . $tokenPort . '/token',
            'revoke_url' => 'http://127.0.0.1:' . $tokenPort . '/revoke',
        ],
        'github' => [
            'client_id' => 'gh-client',
            'client_secret' => 'gh-secret',
            'authorize_url' => 'https://github.com/login/oauth/authorize',
            'token_url' => 'http://127.0.0.1:' . $tokenPort . '/token',
            'revoke_url' => 'http://127.0.0.1:' . $tokenPort . '/revoke',
        ],
    ],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'grant-' . getmypid() . '@simkosi.test');
$start = platform_api($sitePort, '/api/platform', ['op' => 'connector-start', 'provider' => 'google-drive'], $user['token']);
parse_str((string) parse_url($start['data']['url'], PHP_URL_QUERY), $query);
$done = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/connector/callback?code=abc&state=' . $query['state']);
platform_assert($done !== false, 'callback finishes');
$db = file_get_contents($private . '/data/simko.sqlite');
platform_assert(is_string($db) && !str_contains($db, 'access-one') && !str_contains($db, 'refresh-one'), 'tokens are not stored in plaintext');
$status = platform_api($sitePort, '/api/platform', ['op' => 'connectors'], $user['token']);
$byId = [];
foreach ($status['data']['connectors'] as $row) {
    $byId[$row['id']] = $row;
}
platform_assert(!empty($byId['google-drive']['connected']) && empty($byId['github']['connected']), 'status is per connector');
platform_assert(!str_contains(json_encode($status['data']), 'access-one'), 'status does not reveal the access token');
$other = platform_signup($sitePort, 'grant-other-' . getmypid() . '@simkosi.test');
$otherStatus = platform_api($sitePort, '/api/platform', ['op' => 'connectors'], $other['token']);
$otherDrive = $otherStatus['data']['connectors'][0];
platform_assert(empty($otherDrive['connected']), 'another account does not see this grant');
$refresh = platform_api($sitePort, '/api/platform', ['op' => 'connector-refresh', 'provider' => 'google-drive'], $user['token']);
platform_assert($refresh['status'] === 200, 'refresh uses the saved refresh token');
platform_assert(str_contains((string) file_get_contents($log), 'refresh_token'), 'the provider saw a refresh grant');
$bye = platform_api($sitePort, '/api/platform', ['op' => 'connector-disconnect', 'provider' => 'google-drive'], $user['token']);
platform_assert($bye['status'] === 200 && empty($bye['data']['connectors'][0]['connected']), 'disconnect removes the grant');
platform_assert(str_contains((string) file_get_contents($log), '/revoke'), 'disconnect revokes the token at the provider');

platform_stop($site, $sitePipes);
platform_stop($fake, $fakePipes);
fwrite(STDOUT, "connector grant tests passed\n");
