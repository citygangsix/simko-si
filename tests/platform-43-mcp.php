<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// P0 MCP connectors: admin allow-list, sealed tokens, tools/list classification, read tools to the (mock)
// xAI mcp tool, write tools only after Approve (run once by Simko SI), owner-only, caps.
$site = 9146;
$mockPort = 9147;
$mcpPort = 9148;
foreach ([$site, $mockPort, $mcpPort] as $port) {
    platform_require_free_port($port);
}
$bodies = sys_get_temp_dir() . '/simko-p0mcp-bodies-' . getmypid() . '.log';
$mlog = sys_get_temp_dir() . '/simko-p0mcp-fake-' . getmypid() . '.log';
@unlink($bodies);
@unlink($mlog);
putenv('MOCK_XAI_BODIES=' . $bodies);
platform_mock($mockPort);
$env = getenv() ?: [];
$env['FAKE_MCP_LOG'] = $mlog;
$m = proc_open('php -S 127.0.0.1:' . $mcpPort . ' ' . escapeshellarg(__DIR__ . '/fake-mcp.php'), [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $mp, __DIR__, $env);
platform_track($m, $mp);
platform_wait_port($mcpPort);
$private = platform_private('p0mcp', ['mcp' => true, 'approvals' => true, 'search' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [], 'user_ids' => [1]],
    'connectors' => ['token_key' => 'test-only-connector-key-p0'],
    // Tests only: the fake server is plain http on 127.0.0.1.
    'mcp' => ['allowed_hosts' => ['127.0.0.1'], 'allow_http' => true, 'allow_private' => true, 'max_servers' => 2],
]);
[$proc, $pipes] = platform_site($private, $site);
$a = platform_signup($site, 'mcpa-' . getmypid() . '@simkosi.test');
$b = platform_signup($site, 'mcpb-' . getmypid() . '@simkosi.test');
$api = static fn (array $body, array $who) => platform_api($site, '/api/platform', $body, $who['token']);
$url = 'http://127.0.0.1:' . $mcpPort . '/mcp';
$authUrl = 'http://127.0.0.1:' . $mcpPort . '/mcp-auth';
$toolCalls = static fn (): int => count(array_filter(file_exists($mlog) ? (file($mlog, FILE_IGNORE_NEW_LINES) ?: []) : [], fn ($l) => str_starts_with($l, 'tools/call ')));

platform_assert(platform_api($site, '/api/platform', ['op' => 'mcp-list'])['status'] === 401, 'signed-out mcp-list is 401');

// Probe + classification.
$probe = $api(['op' => 'mcp-check', 'url' => $url], $a);
$kinds = array_column($probe['data']['tools'] ?? [], 'kind', 'name');
platform_assert($probe['status'] === 200 && $kinds === ['search_notes' => 'read', 'get_note' => 'read', 'create_note' => 'write', 'delete_note' => 'write'], 'tools/list read/write by readOnlyHint');
$off = $api(['op' => 'mcp-check', 'url' => 'http://localhost:' . $mcpPort . '/mcp'], $a);
platform_assert($off['status'] === 403 && ($off['data']['not_allowed'] ?? '') === 'localhost', 'a host off the allow-list is refused (403)');
platform_assert($api(['op' => 'mcp-check', 'url' => 'ftp://127.0.0.1/mcp'], $a)['status'] === 400, 'non-http(s) is refused');
platform_assert($api(['op' => 'mcp-check', 'url' => 'http://u:p@127.0.0.1:' . $mcpPort . '/mcp'], $a)['status'] === 400, 'user:pass in the URL is refused');

// Save: open server, token server, wrong token.
$s1 = $api(['op' => 'mcp-save', 'label' => 'Notes', 'url' => $url], $a);
platform_assert($s1['status'] === 200 && count($s1['data']['server']['tools']) === 4, 'server saved with its tools');
$allowed = array_column($s1['data']['server']['tools'], 'allowed', 'name');
platform_assert($allowed === ['get_note' => true, 'search_notes' => true, 'create_note' => false, 'delete_note' => false], 'read tools start on, write tools start off');
$sid = (int) $s1['data']['server']['id'];
$bad = $api(['op' => 'mcp-save', 'label' => 'Locked', 'url' => $authUrl, 'bearer_token' => 'wrong'], $a);
platform_assert($bad['status'] === 502 && !empty($bad['data']['mcp_auth']), 'a refused token is reported');
$s2 = $api(['op' => 'mcp-save', 'label' => 'Locked notes', 'url' => $authUrl, 'bearer_token' => 'mcp-test-token'], $a);
platform_assert($s2["status"] === 200 && $s2["data"]["server"]["has_token"] === true, "token server saved: " . json_encode($s2));
$listRaw = json_encode($api(['op' => 'mcp-list'], $a));
platform_assert(!str_contains($listRaw, 'mcp-test-token'), 'the token is never returned');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$cipher = (string) $db->query('SELECT token_cipher FROM mcp_servers WHERE auth_type = \'token\'')->fetchColumn();
platform_assert($cipher !== '' && !str_contains($cipher, 'mcp-test-token'), 'the token is stored sealed');
$cap = $api(['op' => 'mcp-save', 'label' => 'Third', 'url' => $url], $a);
platform_assert($cap['status'] === 409 && ($cap['data']['cap'] ?? '') === 'mcp_servers', 'server cap is 409');

// Owner-only rows and owner-only allow-list.
platform_assert($api(['op' => 'mcp-list'], $b)['data']['servers'] === [], 'another account sees no servers');
foreach (['mcp-tools', 'mcp-delete', 'mcp-refresh'] as $op) {
    platform_assert($api(['op' => $op, 'server_id' => $sid, 'tools' => ['create_note' => true]], $b)['status'] === 404, 'another account gets 404 for ' . $op);
}
platform_assert($api(['op' => 'mcp-hosts'], $b)['status'] === 403 && $api(['op' => 'mcp-hosts-save', 'hosts' => ['evil.example']], $b)['status'] === 403, 'only an owner can see or change the allow-list');
$hosts = $api(['op' => 'mcp-hosts-save', 'hosts' => ['mcp.notion.com', '*.example.org']], $a);
platform_assert($hosts['status'] === 200 && $hosts['data']['allowed_hosts'] === ['127.0.0.1', 'mcp.notion.com', '*.example.org'], 'owner sets the allow-list (config + site setting)');
platform_assert($api(['op' => 'mcp-hosts-save', 'hosts' => ['bad host!']], $a)['status'] === 400, 'invalid host is refused');

// Chat: read tools go to the xAI mcp tool; no write tools yet.
$t = platform_api($site, '/api/simco/turn', ['text' => 'find my grout note'], $a['token']);
$reply = (string) ($t['data']['everyday'] ?? '');
platform_assert($t['status'] === 200 && str_contains($reply, 'simko_s' . $sid . '=get_note|search_notes') && str_contains($reply, '+auth'), 'read tools sent as xAI mcp tools (token server with auth): ' . $reply);
platform_assert(!str_contains($reply, 'create_note') && !str_contains($reply, 'delete_note'), 'write tools are never given to the xAI mcp tool');
platform_assert($toolCalls() === 0, 'nothing was called on the server');

// Turn on create_note: it becomes a function tool that asks first.
platform_assert($api(['op' => 'mcp-tools', 'server_id' => $sid, 'tools' => ['create_note' => true]], $a)['status'] === 200, 'allow create_note');
$w = platform_api($site, '/api/simco/turn', ['text' => 'MCPWRITE add a note to buy grout'], $a['token']);
platform_assert($w['status'] === 200 && ($w['data']['approval']['action'] ?? '') === 'mcp-write' && str_contains($w['data']['approval']['summary'] ?? '', 'create_note'), 'a write tool call becomes an approval card');
platform_assert($toolCalls() === 0, 'nothing runs before Approve');
$aid = (int) $w['data']['approval']['id'];
platform_api($site, '/api/simco/turn', ['text' => 'go', 'approval_id' => $aid], $a['token']);
platform_assert($toolCalls() === 0, 'an unapproved approval id runs nothing');
platform_assert($api(['op' => 'decide', 'approval_id' => $aid, 'decision' => 'approve'], $b)['status'] === 404, 'another account cannot approve it');
platform_assert($api(['op' => 'decide', 'approval_id' => $aid, 'decision' => 'approve'], $a)['status'] === 200, 'Approve');
$done = platform_api($site, '/api/simco/turn', ['text' => 'go ahead', 'approval_id' => $aid], $a['token']);
platform_assert($done['status'] === 200 && str_contains((string) ($done['data']['everyday'] ?? ''), 'Created note "Buy grout"'), 'after Approve Simko SI runs the tool once and reports it: ' . ($done['data']['everyday'] ?? ''));
platform_assert($toolCalls() === 1, 'exactly one tools/call on the server');
$last = (file($mlog, FILE_IGNORE_NEW_LINES) ?: []);
platform_assert((bool) array_filter($last, fn ($l) => str_starts_with($l, 'tools/call') && str_contains($l, 'session=sess-123') && str_contains($l, 'Buy grout')), 'tools/call used the MCP session and the approved arguments');
platform_api($site, '/api/simco/turn', ['text' => 'again', 'approval_id' => $aid], $a['token']);
platform_assert($toolCalls() === 1, 'replaying the approval does not run it again');
$b2 = platform_api($site, '/api/simco/turn', ['text' => 'go', 'approval_id' => $aid], $b['token']);
platform_assert($toolCalls() === 1, 'another account cannot replay it');

// Turning the server off removes its tools from chat; delete.
$api(['op' => 'mcp-tools', 'server_id' => $sid, 'enabled' => false], $a);
$api(['op' => 'mcp-delete', 'server_id' => (int) $s2['data']['server']['id']], $a);
$t2 = platform_api($site, '/api/simco/turn', ['text' => 'hello'], $a['token']);
platform_assert(!str_contains((string) ($t2['data']['everyday'] ?? ''), '[mcp:'), 'disabled/deleted servers are not offered');
platform_assert(count($api(['op' => 'mcp-list'], $a)['data']['servers']) === 1, 'delete');

// Production settings (no test overrides): https only, private addresses refused even when allow-listed.
$prod = platform_private('p0mcpprod', ['mcp' => true], ['connectors' => ['token_key' => 'test-only-connector-key-p0'], 'mcp' => ['allowed_hosts' => ['127.0.0.1', 'localhost']]]);
$check = static function (string $u) use ($prod): string {
    $code = 'require ' . var_export(dirname(__DIR__) . '/public_html/api/mcp.php', true) . '; simko_mcp_check_url(' . var_export($u, true) . '); echo "PASSED";';
    return (string) shell_exec('SIMKOSI_PRIVATE=' . escapeshellarg($prod) . ' php -r ' . escapeshellarg($code) . ' 2>&1');
};
platform_assert(str_contains($check('http://localhost/mcp'), 'must use https'), 'production: plain http is refused');
platform_assert(str_contains($check('https://127.0.0.1/mcp'), 'private network'), 'production: a loopback address is refused');
platform_assert(str_contains($check('https://localhost:8443/mcp'), 'private network'), 'production: a host resolving to loopback is refused');
fwrite(STDOUT, "mcp tests passed\n");
