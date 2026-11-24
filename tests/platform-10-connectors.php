<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 8952;
$private = platform_private('connectors', ['connectors' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'connect-' . getmypid() . '@simkosi.test');
$list = platform_api($sitePort, '/api/platform', ['op' => 'connectors'], $user['token']);
$ready = array_column($list['data']['connectors'] ?? [], 'ready', 'id');
platform_assert(($ready['google-drive'] ?? true) === false && ($ready['google-calendar'] ?? true) === false && ($ready['github'] ?? true) === false, 'Drive, Calendar and GitHub stay hidden without client ids');
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
platform_assert($start['status'] === 200 && str_contains((string) ($start['data']['url'] ?? ''), 'drive.file'), 'Drive asks only for file-level access');
platform_assert(str_contains((string) ($start['data']['url'] ?? ''), 'access_type=offline'), 'Google asks for a refresh token');
platform_assert(!str_contains((string) ($start['data']['url'] ?? ''), 'gmail'), 'the Drive URL has no Gmail scope');
$github = platform_api(8954, '/api/platform', ['op' => 'connector-start', 'provider' => 'github'], $user2['token']);
platform_assert($github['status'] === 200 && str_contains((string) ($github['data']['scope'] ?? ''), 'public_repo'), 'GitHub connector is available');
$cal = platform_api(8954, '/api/platform', ['op' => 'connector-start', 'provider' => 'google-calendar'], $user2['token']);
platform_assert($cal['status'] === 200 && str_contains((string) ($cal['data']['url'] ?? ''), 'calendar.events'), 'Calendar reuses the Drive client and asks for calendar.events');
platform_assert(str_contains((string) ($cal['data']['url'] ?? ''), 'drive-client'), 'Calendar authorize URL uses the Drive client id');
$listOn = platform_api(8954, '/api/platform', ['op' => 'connectors'], $user2['token']);
$byId = [];
foreach ($listOn['data']['connectors'] ?? [] as $row) {
    $byId[$row['id']] = $row;
}
platform_assert(!empty($byId['google-calendar']['disclosure']) && str_contains((string) $byId['google-calendar']['disclosure'], 'xAI'), 'Calendar lists a Google data disclosure');
platform_assert(!empty($byId['google-drive']['disclosure']), 'Drive lists a disclosure');

platform_stop($site2, $site2Pipes);

$signInPrivate = platform_private('connectors-oauth-fallback', ['connectors' => true], [
    'oauth' => [
        'google' => [
            'client_id' => 'signin-client',
            'client_secret' => 'signin-secret',
            'authorize_url' => 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url' => 'https://oauth2.googleapis.com/token',
        ],
    ],
    'connectors' => [
        'google-drive' => ['client_id' => '', 'client_secret' => ''],
    ],
]);
[$site3, $site3Pipes] = platform_site($signInPrivate, 8956);
$user3 = platform_signup(8956, 'connect-fallback-' . getmypid() . '@simkosi.test');
$calFb = platform_api(8956, '/api/platform', ['op' => 'connector-start', 'provider' => 'google-calendar'], $user3['token']);
platform_assert($calFb['status'] === 200 && str_contains((string) ($calFb['data']['url'] ?? ''), 'signin-client'), 'Calendar falls back to the Google sign-in client');
platform_stop($site3, $site3Pipes);
fwrite(STDOUT, "connector tests passed\n");
