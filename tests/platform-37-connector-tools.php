<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Drive (drive.file + picked files) and GitHub read tools against fake Google/GitHub APIs.
$apiPort = 9103;
$sitePort = 9102;
$log = sys_get_temp_dir() . '/simko-api-log-' . getmypid() . '.txt';
platform_require_free_port($apiPort);
$env = getenv() ?: [];
$env['SIMKO_API_LOG'] = $log;
$fake = proc_open('php -S 127.0.0.1:' . $apiPort . ' ' . escapeshellarg(__DIR__ . '/fake-apis.php'), [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $fakePipes, dirname(__DIR__), $env);
platform_wait_port($apiPort);
$api = 'http://127.0.0.1:' . $apiPort;
$private = platform_private('connector-tools', ['connectors' => true], [
    'connectors' => [
        'token_key' => 'test-only-connector-key',
        'google-drive' => ['client_id' => 'drive-client', 'client_secret' => 'drive-secret', 'token_url' => $api . '/token', 'revoke_url' => $api . '/revoke', 'api_base' => $api, 'picker_api_key' => 'picker-key-test', 'app_id' => '740407453113'],
        'github' => ['client_id' => 'gh-client', 'client_secret' => 'gh-secret', 'token_url' => $api . '/token', 'api_base' => $api],
    ],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$u = platform_signup($sitePort, 'tools-' . getmypid() . '@simkosi.test');
$v = platform_signup($sitePort, 'tools-v-' . getmypid() . '@simkosi.test');

$notYet = platform_api($sitePort, '/api/platform', ['op' => 'drive-picker'], $u['token']);
platform_assert($notYet['status'] === 404, 'the picker needs Drive connected first');
$connect = static function (string $provider, string $token) use ($sitePort): void {
    $start = platform_api($sitePort, '/api/platform', ['op' => 'connector-start', 'provider' => $provider], $token);
    parse_str((string) parse_url($start['data']['url'], PHP_URL_QUERY), $q);
    $ctx = stream_context_create(['http' => ['follow_location' => 0, 'ignore_errors' => true]]);
    file_get_contents('http://127.0.0.1:' . $sitePort . '/api/connector/callback?code=abc&state=' . $q['state'], false, $ctx);
    $loc = '';
    foreach ($http_response_header ?? [] as $h) {
        if (stripos($h, 'Location:') === 0) {
            $loc = trim(substr($h, 9));
        }
    }
    platform_assert($loc === '/?connected=' . $provider, $provider . ' callback returns to the site with ?connected=');
};
$connect('google-drive', $u['token']);
$list = platform_api($sitePort, '/api/platform', ['op' => 'connectors'], $u['token']);
$drive = array_values(array_filter($list['data']['connectors'], static fn ($r) => $r['id'] === 'google-drive'))[0];
platform_assert($drive['connected'] === true && $drive['picker'] === true, 'Drive shows connected with the file picker');
$pk = platform_api($sitePort, '/api/platform', ['op' => 'drive-picker'], $u['token']);
platform_assert($pk['status'] === 200 && $pk['data']['access_token'] === 'access-one' && $pk['data']['api_key'] === 'picker-key-test' && $pk['data']['app_id'] === '740407453113', 'the picker gets the person\'s token, the browser key and the app id');
platform_assert(platform_api($sitePort, '/api/platform', ['op' => 'drive-picker'], $v['token'])['status'] === 404, 'another person gets no Drive token');

$save = platform_api($sitePort, '/api/platform', ['op' => 'drive-picks-save', 'files' => [
    ['id' => 'doc1234567890', 'name' => 'Trip plan', 'mimeType' => 'application/vnd.google-apps.document'],
    ['id' => 'txt1234567890', 'name' => 'notes.txt', 'mimeType' => 'text/plain'],
    ['id' => 'png1234567890', 'name' => 'photo.png', 'mimeType' => 'image/png'],
    ['id' => 'bad id with spaces', 'name' => 'x'],
]], $u['token']);
platform_assert($save['status'] === 200 && $save['data']['saved'] === 3 && count($save['data']['files']) === 3, 'picked files are saved (bad ids dropped)');
platform_assert(platform_api($sitePort, '/api/platform', ['op' => 'drive-picks-save', 'files' => [['id' => 'doc1234567890', 'name' => 'x']]], $v['token'])['status'] === 404, 'no picks without a Drive connection');

// Tool functions (used by function calling) run in-process against the fake APIs.
$code = 'require ' . var_export(dirname(__DIR__) . '/public_html/api/connector-tools.php', true) . ';'
    . '$uid = (int) simko_db()->query("SELECT id FROM users WHERE email LIKE \'tools-%\' AND email NOT LIKE \'tools-v-%\'")->fetchColumn();'
    . '$vid = (int) simko_db()->query("SELECT id FROM users WHERE email LIKE \'tools-v-%\'")->fetchColumn();'
    . 'echo json_encode(['
    . '"picks" => simko_drive_picks($uid),'
    . '"doc" => simko_drive_read($uid, "doc1234567890"),'
    . '"txt" => simko_drive_read($uid, "txt1234567890"),'
    . '"png" => simko_drive_read($uid, "png1234567890"),'
    . '"unpicked" => simko_drive_read($uid, "zzz1234567890"),'
    . '"other" => simko_drive_read($vid, "doc1234567890"),'
    . ']);';
$out = json_decode((string) shell_exec('SIMKOSI_PRIVATE=' . escapeshellarg($private) . ' php -r ' . escapeshellarg($code) . ' 2>&1'), true);
platform_assert(is_array($out) && count($out['picks']) === 3, 'list picked files');
platform_assert(str_contains((string) ($out['doc']['text'] ?? ''), 'Lisbon'), 'a Google Doc is exported as text');
platform_assert(str_contains((string) ($out['txt']['text'] ?? ''), 'Max'), 'a text file is downloaded');
platform_assert(!empty($out['png']['error']) && empty($out['png']['text']), 'a picture is refused politely');
platform_assert(str_contains((string) ($out['unpicked']['error'] ?? ''), 'not picked'), 'an unpicked file cannot be read');
platform_assert(str_contains((string) ($out['other']['error'] ?? ''), 'not picked'), 'another person cannot read my picked file');

$connect('github', $u['token']);
$code2 = 'require ' . var_export(dirname(__DIR__) . '/public_html/api/connector-tools.php', true) . ';'
    . '$uid = (int) simko_db()->query("SELECT id FROM users WHERE email LIKE \'tools-%\' AND email NOT LIKE \'tools-v-%\'")->fetchColumn();'
    . 'echo json_encode(['
    . '"repos" => simko_github_list_repos($uid),'
    . '"file" => simko_github_read_file($uid, "citygangsix/simko-si", "README.md"),'
    . '"dir" => simko_github_read_file($uid, "citygangsix/simko-si", "docs"),'
    . '"evil" => simko_github_read_file($uid, "citygangsix/simko-si", "../../etc/passwd"),'
    . '"badrepo" => simko_github_list_issues($uid, "https://evil.example/x"),'
    . '"issues" => simko_github_list_issues($uid, "citygangsix/simko-si"),'
    . ']);';
$gh = json_decode((string) shell_exec('SIMKOSI_PRIVATE=' . escapeshellarg($private) . ' php -r ' . escapeshellarg($code2) . ' 2>&1'), true);
platform_assert(is_array($gh) && count($gh['repos']['repos'] ?? []) === 2 && $gh['repos']['repos'][0]['full_name'] === 'citygangsix/simko-si', 'GitHub: list my repos');
platform_assert(str_contains((string) ($gh['file']['text'] ?? ''), 'calm assistant'), 'GitHub: read a file');
platform_assert(($gh['dir']['entries'] ?? []) === ['a.md', 'img/'], 'GitHub: a folder path lists its entries');
platform_assert(!empty($gh['evil']['error']) && !empty($gh['badrepo']['error']), 'GitHub: path tricks and odd repo names are refused');
platform_assert(count($gh['issues']['issues'] ?? []) === 1 && $gh['issues']['issues'][0]['number'] === 7, 'GitHub: list open issues (pull requests left out)');

$rm = platform_api($sitePort, '/api/platform', ['op' => 'drive-pick-remove', 'file_id' => 'png1234567890'], $u['token']);
platform_assert(count($rm['data']['files'] ?? []) === 2, 'a picked file can be removed');
$bye = platform_api($sitePort, '/api/platform', ['op' => 'connector-disconnect', 'provider' => 'google-drive'], $u['token']);
platform_assert($bye['status'] === 200 && platform_api($sitePort, '/api/platform', ['op' => 'drive-picks'], $u['token'])['data']['files'] === [], 'disconnecting Drive forgets the picked files');
$logText = (string) @file_get_contents($log);
platform_assert(!str_contains($logText, 'drive.readonly'), 'nothing asks for drive.readonly');
platform_stop($site, $sitePipes);
platform_stop($fake, $fakePipes);
