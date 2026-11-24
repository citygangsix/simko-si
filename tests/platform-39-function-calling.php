<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Function calling: site tools, Drive/GitHub tools only when connected, approval before create_routine, tools_used chips.
$xaiPort = 9123;
$apiPort = 9124;
$sitePort = 9122;
platform_require_free_port($xaiPort);
platform_require_free_port($apiPort);
$xlog = sys_get_temp_dir() . '/simko-xai-tools-' . getmypid() . '.txt';
$alog = sys_get_temp_dir() . '/simko-api-log39-' . getmypid() . '.txt';
@unlink($xlog);
$env = getenv() ?: [];
$env['SIMKO_XAI_LOG'] = $xlog;
$env['SIMKO_API_LOG'] = $alog;
$x = proc_open('php -S 127.0.0.1:' . $xaiPort . ' ' . escapeshellarg(__DIR__ . '/fake-xai-tools.php'), [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $xp, __DIR__, $env);
platform_track($x, $xp);
$f = proc_open('php -S 127.0.0.1:' . $apiPort . ' ' . escapeshellarg(__DIR__ . '/fake-apis.php'), [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $fp, __DIR__, $env);
platform_track($f, $fp);
platform_wait_port($xaiPort);
platform_wait_port($apiPort);
$api = 'http://127.0.0.1:' . $apiPort;
$lastBody = static function () use ($xlog): array {
    $lines = file($xlog, FILE_IGNORE_NEW_LINES) ?: [];
    return json_decode((string) end($lines), true)['body'] ?? [];
};
$offered = static function (array $body): array {
    return array_values(array_filter(array_map(static fn ($t) => (string) ($t['name'] ?? ($t['function']['name'] ?? '')), $body['tools'] ?? [])));
};

foreach (['responses' => true, 'completions' => false] as $style => $search) {
    $private = platform_private('fncall-' . $style, ['memory' => true, 'routines' => true, 'approvals' => true, 'connectors' => true, 'search' => $search, 'paywall' => false], [
        'xai_base_url' => 'http://127.0.0.1:' . $xaiPort . '/v1',
        'connectors' => [
            'token_key' => 'test-only-connector-key',
            'google-drive' => ['client_id' => 'd', 'client_secret' => 's', 'token_url' => $api . '/token', 'revoke_url' => $api . '/revoke', 'api_base' => $api, 'picker_api_key' => 'k', 'app_id' => '1'],
            'github' => ['client_id' => 'g', 'client_secret' => 's', 'token_url' => $api . '/token', 'api_base' => $api],
        ],
    ]);
    [$site, $sp] = platform_site($private, $sitePort);
    $u = platform_signup($sitePort, 'fn-' . $style . getmypid() . '@simkosi.test');
    $turn = static fn (string $text, array $extra = []) => platform_api($sitePort, '/api/simco/turn', $extra + ['text' => $text, 'tz' => 'America/New_York'], $u['token']);

    // A plain chat offers no function tools and keeps streaming.
    $plain = platform_api($sitePort, '/api/simco/turn', ['text' => 'hello there', 'stream' => true], $u['token']);
    $names = $offered($lastBody());
    platform_assert(!array_intersect($names, ['save_memory', 'create_routine', 'drive_list_picked_files', 'github_list_repos']) && !empty($lastBody()['stream']), "[$style] plain chat: no function tools, still streams");

    // remember that my dog is Max -> save_memory, chip, saved once.
    $r = $turn('Please remember that my dog is Max');
    $names = $offered($lastBody());
    platform_assert($r['status'] === 200 && ($r['data']['tools_used'] ?? []) === ['save_memory'], "[$style] save_memory ran and is reported for the Used chip");
    platform_assert(!in_array('drive_list_picked_files', $names, true) && !in_array('github_list_repos', $names, true), "[$style] Drive and GitHub tools are not offered before they are connected");
    $mem = platform_api($sitePort, '/api/platform', ['op' => 'memories'], $u['token']);
    $facts = array_column($mem['data']['memories'] ?? [], 'fact');
    platform_assert(in_array('My dog is Max', $facts, true) && count($facts) === 1, "[$style] the memory is saved once: " . json_encode($facts));

    // create_routine waits for Approve.
    $r = $turn('Make a homework routine at 7:30 pm');
    platform_assert($r['status'] === 200 && ($r['data']['approval']['action'] ?? '') === 'routine-create' && str_contains($r['data']['approval']['summary'] ?? '', 'Homework reminder daily at 19:30'), "[$style] create_routine asks for approval first");
    $rows = platform_api($sitePort, '/api/platform', ['op' => 'routines'], $u['token']);
    platform_assert(($rows['data']['routines'] ?? []) === [], "[$style] nothing is created before Approve");
    $aid = (int) $r['data']['approval']['id'];
    platform_assert(platform_api($sitePort, '/api/simco/turn', ['text' => 'Make a homework routine at 7:30 pm', 'approval_id' => $aid], $u['token'])['status'] === 200, "[$style] a turn with an unapproved id answers");
    $rows = platform_api($sitePort, '/api/platform', ['op' => 'routines'], $u['token']);
    platform_assert(($rows['data']['routines'] ?? []) === [], "[$style] an unapproved id runs nothing");
    $d = platform_api($sitePort, '/api/platform', ['op' => 'decide', 'approval_id' => $aid, 'decision' => 'approve'], $u['token']);
    platform_assert($d['status'] === 200, "[$style] Approve");
    $r2 = $turn('Make a homework routine at 7:30 pm', ['approval_id' => $aid]);
    platform_assert($r2['status'] === 200 && str_contains($r2['data']['everyday'] ?? '', 'routine is saved') && in_array('create_routine', $r2['data']['tools_used'] ?? [], true), "[$style] after Approve the routine is created and reported");
    platform_assert(!str_contains($r2['data']['everyday'], 'create_routine'), "[$style] create_routine is not offered again on the approved turn");
    $rows = platform_api($sitePort, '/api/platform', ['op' => 'routines'], $u['token']);
    platform_assert(count($rows['data']['routines'] ?? []) === 1 && $rows['data']['routines'][0]['hour'] === 19 && $rows['data']['routines'][0]['minute'] === 30, "[$style] exactly one routine at 19:30");
    $turn('Make a homework routine at 7:30 pm', ['approval_id' => $aid]);
    $rows = platform_api($sitePort, '/api/platform', ['op' => 'routines'], $u['token']);
    platform_assert(count($rows['data']['routines'] ?? []) === 1, "[$style] replaying the approval does not create a second routine");
    $r3 = $turn('What routines do I have?');
    platform_assert(($r3['data']['tools_used'] ?? []) === ['list_routines'] && str_contains($r3['data']['everyday'], 'homework'), "[$style] list_routines");

    // A tool the model was not offered is refused.
    $o = $turn('homework routine again, sneak it in', ['approval_id' => $aid]);
    platform_assert(empty($o['data']['approval']) && str_contains($o['data']['everyday'] ?? '', 'not available') && count(platform_api($sitePort, '/api/platform', ['op' => 'routines'], $u['token'])['data']['routines']) === 1, "[$style] an un-offered tool call is refused");

    // Connect Drive + GitHub: their tools appear.
    foreach (['google-drive', 'github'] as $provider) {
        $start = platform_api($sitePort, '/api/platform', ['op' => 'connector-start', 'provider' => $provider], $u['token']);
        parse_str((string) parse_url($start['data']['url'], PHP_URL_QUERY), $q);
        @file_get_contents('http://127.0.0.1:' . $sitePort . '/api/connector/callback?code=abc&state=' . $q['state'], false, stream_context_create(['http' => ['follow_location' => 0, 'ignore_errors' => true]]));
    }
    platform_api($sitePort, '/api/platform', ['op' => 'drive-picks-save', 'files' => [['id' => 'doc1234567890', 'name' => 'Trip plan', 'mimeType' => 'application/vnd.google-apps.document']]], $u['token']);
    $p2 = platform_api($sitePort, '/api/simco/turn', ['text' => 'hello again', 'stream' => true], $u['token']);
    $names = $offered($lastBody());
    platform_assert(count(array_intersect($names, ['drive_list_picked_files', 'drive_read_picked_file', 'github_list_repos', 'github_read_file', 'github_list_issues'])) === 5, "[$style] connected: Drive and GitHub tools are offered");
    $dr = $turn('Read my trip plan and tell me where I fly');
    platform_assert(($dr['data']['tools_used'] ?? []) === ['drive_list_picked_files', 'drive_read_picked_file'] && str_contains($dr['data']['everyday'], 'Lisbon'), "[$style] Drive: list picked files then read one");
    $gh = $turn('List my repos');
    platform_assert(($gh['data']['tools_used'] ?? []) === ['github_list_repos'] && str_contains($gh['data']['everyday'], 'citygangsix/simko-si'), "[$style] GitHub: list repos");

    // Child profile: no site tools.
    platform_stop($site, $sp);
}

// Page has the chip row and the in-chat Approve button.
$html = (string) file_get_contents(dirname(__DIR__) . '/public_html/index.html');
$js = (string) file_get_contents(dirname(__DIR__) . '/public_html/assets/simco-app.js');
platform_assert(str_contains($html, 'id="usedTools"') && str_contains($html, 'id="approvalCards"') && str_contains($html, 'id="chatApprovalTpl"') && str_contains($js, '"Used: "') && str_contains($js, 'showChatApproval'), 'chat shows Used chips and an in-chat Approve button');
@unlink($xlog);
@unlink($alog);
echo "platform-39-function-calling: ok\n";
