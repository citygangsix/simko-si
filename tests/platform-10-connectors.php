<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 8952;
$private = platform_private('connectors', ['connectors' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'connect-' . getmypid() . '@simkosi.test');
$list = platform_api($sitePort, '/api/platform', ['op' => 'connectors'], $user['token']);
$ready = array_column($list['data']['connectors'] ?? [], 'ready', 'id');
platform_assert(($ready['google-drive'] ?? true) === false && ($ready['github'] ?? true) === false, 'both connectors are hidden without client ids');
$drive = platform_api($sitePort, '/api/platform', ['op' => 'connector-start', 'provider' => 'google-drive'], $user['token']);
platform_assert($drive['status'] === 404, 'Drive does not start while hidden');
$gmail = platform_api($sitePort, '/api/platform', ['op' => 'connector-start', 'provider' => 'gmail'], $user['token']);
platform_assert($gmail['status'] === 400 && str_contains((string) ($gmail['data']['error'] ?? ''), 'Gmail'), 'Gmail is refused');
$bank = platform_api($sitePort, '/api/platform', ['op' => 'connector-start', 'provider' => 'bank'], $user['token']);
platform_assert($bank['status'] === 400, 'banking is refused');
platform_stop($site, $sitePipes);

$readyPrivate = platform_private('connectors-on', ['connectors' => true], [
    'connectors' => [
        'google-drive' => ['client_id' => 'drive-client', 'authorize_url' => 'https://accounts.google.com/o/oauth2/v2/auth'],
        'github' => ['client_id' => 'gh-client', 'authorize_url' => 'https://github.com/login/oauth/authorize'],
    ],
]);
[$site2, $site2Pipes] = platform_site($readyPrivate, 8954);
$user2 = platform_signup(8954, 'connect-on-' . getmypid() . '@simkosi.test');
$start = platform_api(8954, '/api/platform', ['op' => 'connector-start', 'provider' => 'google-drive'], $user2['token']);
platform_assert($start['status'] === 200 && str_contains((string) ($start['data']['url'] ?? ''), 'drive.readonly'), 'Drive asks only for read-only');
platform_assert(!str_contains((string) ($start['data']['url'] ?? ''), 'gmail'), 'the Drive URL has no Gmail scope');
$github = platform_api(8954, '/api/platform', ['op' => 'connector-start', 'provider' => 'github'], $user2['token']);
platform_assert($github['status'] === 200 && str_contains((string) ($github['data']['scope'] ?? ''), 'public_repo'), 'GitHub connector is available');

platform_stop($site2, $site2Pipes);
fwrite(STDOUT, "connector tests passed\n");
