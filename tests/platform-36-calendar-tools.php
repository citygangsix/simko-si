<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$mockPort = 9180;
$tokenPort = 9181;
$calPort = 9182;
$sitePort = 9183;
platform_require_free_port($mockPort);
platform_require_free_port($tokenPort);
platform_require_free_port($calPort);
platform_require_free_port($sitePort);

[$mock, $mockPipes] = platform_mock($mockPort);

$store = sys_get_temp_dir() . '/simko-cal-store-' . getmypid() . '.json';
$log = sys_get_temp_dir() . '/simko-cal-log-' . getmypid() . '.txt';
file_put_contents($store, json_encode([
    'evt-seed' => [
        'id' => 'evt-seed',
        'summary' => 'Team standup',
        'start' => ['dateTime' => '2026-11-24T09:00:00-05:00'],
        'end' => ['dateTime' => '2026-11-24T09:30:00-05:00'],
        'description' => '',
        'location' => '',
    ],
]));
$env = getenv();
if (!is_array($env)) {
    $env = [];
}
$env['SIMKO_CALENDAR_STORE'] = $store;
$env['SIMKO_CALENDAR_LOG'] = $log;
$calCmd = 'php -S 127.0.0.1:' . $calPort . ' ' . escapeshellarg(__DIR__ . '/fake-calendar.php');
$cal = proc_open($calCmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $calPipes, dirname(__DIR__), $env);
platform_wait_port($calPort);

$tokenLog = sys_get_temp_dir() . '/simko-cal-token-' . getmypid() . '.txt';
$tokenEnv = $env;
$tokenEnv['SIMKO_CONNECTOR_LOG'] = $tokenLog;
$tokCmd = 'php -S 127.0.0.1:' . $tokenPort . ' ' . escapeshellarg(__DIR__ . '/fake-connector.php');
$tok = proc_open($tokCmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $tokPipes, dirname(__DIR__), $tokenEnv);
platform_wait_port($tokenPort);

$private = platform_private('calendar-tools', [
    'connectors' => true,
    'approvals' => true,
    'search' => false,
    'paywall' => false,
], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'connectors' => [
        'token_key' => 'test-only-connector-key',
        'google-drive' => [
            'client_id' => 'drive-client',
            'client_secret' => 'drive-secret',
            'authorize_url' => 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url' => 'http://127.0.0.1:' . $tokenPort . '/token',
            'revoke_url' => 'http://127.0.0.1:' . $tokenPort . '/revoke',
        ],
        'google-calendar' => [
            'api_base' => 'http://127.0.0.1:' . $calPort,
        ],
    ],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'cal-' . getmypid() . '@simkosi.test');
$token = $user['token'];

$start = platform_api($sitePort, '/api/platform', ['op' => 'connector-start', 'provider' => 'google-calendar'], $token);
platform_assert($start['status'] === 200, 'calendar start works');
parse_str((string) parse_url($start['data']['url'], PHP_URL_QUERY), $query);
file_get_contents('http://127.0.0.1:' . $sitePort . '/api/connector/callback?code=abc&state=' . $query['state']);

$listTurn = platform_api($sitePort, '/api/simco/turn', [
    'text' => "what's on my calendar this week",
    'stream' => false,
], $token);
platform_assert($listTurn['status'] === 200 && str_contains((string) ($listTurn['data']['everyday'] ?? ''), 'Team standup'), 'list turn names the seeded event');

$held = platform_api($sitePort, '/api/simco/turn', [
    'text' => 'Create a test event called Simko SI test tomorrow at 3pm',
    'stream' => false,
], $token);
platform_assert($held['status'] === 200 && !empty($held['data']['approval']['id']), 'create waits for approval');
$before = json_decode((string) file_get_contents($store), true);
$beforeIds = is_array($before) ? array_keys($before) : [];
platform_assert(is_array($before) && !in_array('Simko SI test', array_column($before, 'summary'), true), 'event is not created before approval');

platform_api($sitePort, '/api/platform', [
    'op' => 'decide',
    'approval_id' => $held['data']['approval']['id'],
    'decision' => 'approve',
], $token);
$created = platform_api($sitePort, '/api/simco/turn', [
    'text' => 'Create a test event called Simko SI test tomorrow at 3pm',
    'stream' => false,
    'approval_id' => $held['data']['approval']['id'],
], $token);
platform_assert($created['status'] === 200 && str_contains((string) ($created['data']['everyday'] ?? ''), 'Simko SI test'), 'approved create is confirmed in the reply');
$after = json_decode((string) file_get_contents($store), true);
$createdId = '';
if (is_array($after)) {
    foreach ($after as $id => $item) {
        if (is_array($item) && ($item['summary'] ?? '') === 'Simko SI test') {
            $createdId = (string) $id;
        }
    }
}
platform_assert($createdId !== '', 'event exists in Calendar after approval');

$holdDel = platform_api($sitePort, '/api/simco/turn', [
    'text' => 'Delete the event Simko SI test (' . $createdId . ')',
    'stream' => false,
], $token);
platform_assert(!empty($holdDel['data']['approval']['id']), 'delete waits for approval');
platform_api($sitePort, '/api/platform', [
    'op' => 'decide',
    'approval_id' => $holdDel['data']['approval']['id'],
    'decision' => 'approve',
], $token);
$deleted = platform_api($sitePort, '/api/simco/turn', [
    'text' => 'Delete the event Simko SI test (' . $createdId . ')',
    'stream' => false,
    'approval_id' => $holdDel['data']['approval']['id'],
], $token);
platform_assert($deleted['status'] === 200, 'approved delete returns a reply');
$final = json_decode((string) file_get_contents($store), true);
platform_assert(is_array($final) && !isset($final[$createdId]), 'event is removed from Calendar after approved delete');
platform_assert(isset($final['evt-seed']), 'the seeded event is left alone');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
platform_stop($cal, $calPipes);
platform_stop($tok, $tokPipes);
@unlink($store);
@unlink($log);
@unlink($tokenLog);
fwrite(STDOUT, "calendar tool tests passed\n");
