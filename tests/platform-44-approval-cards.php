<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// In-chat Yes/No approval cards (APPROVAL-PROMPT-SPEC): task-start, mcp-spend, paywall-on (owner only),
// mcp-token-share (first use per connector login). Each: pending row, Yes runs once, a second Yes does not
// rerun, No runs nothing, expired cannot be approved. All xAI calls mocked; Stripe is never called.
$site = 9150;
$mockPort = 9151;
$mcpPort = 9152;
$site2 = 9153;
$site3 = 9154;
foreach ([$site, $mockPort, $mcpPort, $site2, $site3] as $port) {
    platform_require_free_port($port);
}
// Never let a Stripe key from the shell reach these test servers: the card reads test mode from config only.
foreach (['STRIPE_SECRET_KEY', 'STRIPE_RESTRICTED_KEY', 'STRIPE_PRICE_ID', 'STRIPE_API_BASE', 'STRIPE_WEBHOOK_SECRET'] as $stripeEnv) {
    putenv($stripeEnv);
}
$calls = sys_get_temp_dir() . '/simko-p0cards-calls-' . getmypid() . '.log';
$mlog = sys_get_temp_dir() . '/simko-p0cards-mcp-' . getmypid() . '.log';
@unlink($calls);
@unlink($mlog);
putenv('MOCK_XAI_LOG=' . $calls);
platform_mock($mockPort);
$env = getenv() ?: [];
$env['FAKE_MCP_LOG'] = $mlog;
$m = proc_open('php -S 127.0.0.1:' . $mcpPort . ' ' . escapeshellarg(__DIR__ . '/fake-mcp.php'), [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $mp, __DIR__, $env);
platform_track($m, $mp);
platform_wait_port($mcpPort);

$common = [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [], 'user_ids' => [1]],
    'connectors' => ['token_key' => 'test-only-connector-key-p0'],
    'spend_caps' => ['owner_daily_usd' => 5.0, 'user_daily_usd' => 1.0, 'site_daily_usd' => 10.0, 'timezone' => 'America/New_York'],
    // Test-mode Stripe only, pointed at a closed port: nothing in these cards may call Stripe.
    'stripe' => ['secret_key' => 'sk_test_localonly4242', 'account_id' => 'acct_TEST9876', 'price_id' => 'price_test_1', 'api_base' => 'http://127.0.0.1:9'],
];
$flags = ['approvals' => true, 'tasks' => true, 'mcp' => true, 'search' => true, 'paywall' => false];
$private = platform_private('p0cards', $flags, $common + [
    'mcp' => ['allowed_hosts' => ['127.0.0.1'], 'allow_http' => true, 'allow_private' => true],
]);
[$proc, $pipes] = platform_site($private, $site);
$owner = platform_signup($site, 'cardsa-' . getmypid() . '@simkosi.test');
$other = platform_signup($site, 'cardsb-' . getmypid() . '@simkosi.test');
$api = static fn (array $body, array $who) => platform_api($site, '/api/platform', $body, $who['token']);
$turn = static fn (array $body, array $who) => platform_api($site, '/api/simco/turn', $body, $who['token']);
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$responses = static fn (): int => count(array_filter(file_exists($calls) ? (file($calls, FILE_IGNORE_NEW_LINES) ?: []) : [], fn ($l) => $l === '/v1/responses'));
$toolCalls = static fn (): int => count(array_filter(file_exists($mlog) ? (file($mlog, FILE_IGNORE_NEW_LINES) ?: []) : [], fn ($l) => str_starts_with($l, 'tools/call ')));
$status = static fn (int $id): string => (string) $db->query('SELECT status FROM approvals WHERE id = ' . $id)->fetchColumn();
$ranCount = static fn (int $id): int => (int) $db->query("SELECT COUNT(*) FROM audit_log WHERE summary LIKE 'Ran approval " . $id . ":%'")->fetchColumn();
$session = static function (array $who) use ($site): string {
    $r = platform_api($site, '/api/sessions', ['op' => 'create', 'title' => 'Cards'], $who['token']);
    return (string) $r['data']['session']['id'];
};
$chatA = $session($owner);

// ---- 1. task-start from a Grok tool call (mode create) ----
$t = $turn(['text' => 'TASKCREATE every morning give me the news', 'session_id' => $chatA, 'tz' => 'America/New_York'], $owner);
$card = $t['data']['approval'] ?? [];
platform_assert($t['status'] === 200 && ($card['action'] ?? '') === 'task-start' && $card['status'] === 'pending', 'Grok create_task becomes a pending task-start card: ' . json_encode($t['data']));
platform_assert($status((int) $card['id']) === 'pending', 'task-start: pending row in approvals');
platform_assert(str_contains($card['title'], "Start scheduled task 'Morning news'") && str_contains($card['what'], 'three top headlines')
    && str_contains($card['cost_label'], 'About $0.020 per run') && str_contains($card['cost_label'], 'left') && str_contains($card['where'], 'Every day at 7:15 AM (America/New_York), next run'),
    'task card shows title, what, cost + cap left, where: ' . json_encode($card));
platform_assert((int) $db->query('SELECT COUNT(*) FROM tasks')->fetchColumn() === 0, 'nothing is saved before Yes');
$pending = $api(['op' => 'approvals-pending', 'session_id' => $chatA], $owner)['data']['approvals'] ?? [];
platform_assert(count($pending) === 1 && (int) $pending[0]['id'] === (int) $card['id'] && $pending[0]['session_id'] === $chatA, 'reopening the chat lists the pending card');
platform_assert(($api(['op' => 'approvals-pending', 'session_id' => $session($owner)], $owner)['data']['approvals'] ?? null) === [], 'another chat does not show it');
platform_assert($api(['op' => 'decide', 'approval_id' => (int) $card['id'], 'decision' => 'approve'], $other)['status'] === 404, 'another account cannot decide it');
$yes = $api(['op' => 'decide', 'approval_id' => (int) $card['id'], 'decision' => 'approve'], $owner);
platform_assert($yes['status'] === 200 && $yes['data']['approval']['status'] === 'approved', 'Yes');
$run = $turn(['text' => 'TASKCREATE every morning give me the news', 'session_id' => $chatA, 'approval_id' => (int) $card['id']], $owner);
platform_assert($run['status'] === 200 && str_contains((string) ($run['data']['approval_result'] ?? ''), "Started 'Morning news'") && ($run['data']['approval_card']['status'] ?? '') === 'approved',
    'Yes runs it on the next turn, with a result for the chip: ' . json_encode($run['data']));
$row = $db->query('SELECT * FROM tasks')->fetch(PDO::FETCH_ASSOC);
platform_assert($row && (int) $row['enabled'] === 1 && $row['name'] === 'Morning news', 'the task exists and is on');
$turn(['text' => 'again', 'session_id' => $chatA, 'approval_id' => (int) $card['id']], $owner);
$api(['op' => 'task-toggle', 'task_id' => (int) $row['id'], 'enabled' => true, 'approval_id' => (int) $card['id']], $owner);
platform_assert((int) $db->query('SELECT COUNT(*) FROM tasks')->fetchColumn() === 1 && $ranCount((int) $card['id']) === 1, 'replaying the approved card does not run it again');
platform_assert($api(['op' => 'decide', 'approval_id' => (int) $card['id'], 'decision' => 'approve'], $owner)['status'] === 404, 'a second Yes is refused');
$taskId = (int) $row['id'];

// ---- 2. task-save with enabled on -> card; No runs nothing; Grok is told ----
$base = ['name' => 'Evening note', 'prompt' => 'One calm line for tonight.', 'freq' => 'daily', 'hour' => 21, 'minute' => 0, 'tz' => 'America/New_York'];
$saved = $api(['op' => 'task-save', 'session_id' => $chatA] + $base, $owner);
$noCard = $saved['data']['approval'] ?? [];
platform_assert($saved['status'] === 200 && $saved['data']['task']['enabled'] === false && ($noCard['action'] ?? '') === 'task-start', 'task-save with enabled on is saved paused with a card');
$eveningId = (int) $saved['data']['task']['id'];
$pausedSave = $api(['op' => 'task-save', 'enabled' => false, 'name' => 'Paused one'] + $base, $owner);
platform_assert($pausedSave['status'] === 200 && !isset($pausedSave['data']['approval']) && $pausedSave['data']['task']['enabled'] === false, 'saving paused needs no card');
$no = $api(['op' => 'decide', 'approval_id' => (int) $noCard['id'], 'decision' => 'decline'], $owner);
platform_assert($no['status'] === 200 && $status((int) $noCard['id']) === 'declined', 'No');
platform_assert($api(['op' => 'task-toggle', 'task_id' => $eveningId, 'enabled' => true, 'approval_id' => (int) $noCard['id']], $owner)['status'] === 403, 'a declined card cannot be applied');
$turn(['text' => 'hello', 'session_id' => $chatA, 'approval_id' => (int) $noCard['id']], $owner);
platform_assert((int) $db->query('SELECT enabled FROM tasks WHERE id = ' . $eveningId)->fetchColumn() === 0 && $ranCount((int) $noCard['id']) === 0, 'No runs nothing');
platform_assert($api(['op' => 'decide', 'approval_id' => (int) $noCard['id'], 'decision' => 'approve'], $owner)['status'] === 404, 'Yes after No is refused');
$told = $turn(['text' => 'ok what now', 'session_id' => $chatA], $owner);
platform_assert(str_contains((string) ($told['data']['everyday'] ?? ''), '[declined-noted]'), 'the next turn tells Grok about the No (do not retry): ' . json_encode($told['data']));

// ---- 3. edits: rename keeps it on; prompt/schedule change needs a new card; pause/delete never gated ----
$tRow = $db->query('SELECT * FROM tasks WHERE id = ' . $taskId)->fetch(PDO::FETCH_ASSOC);
$edit = ['op' => 'task-save', 'id' => $taskId, 'name' => 'Morning news v2', 'prompt' => $tRow['prompt'], 'freq' => $tRow['freq'], 'hour' => (int) $tRow['hour'], 'minute' => (int) $tRow['minute'], 'tz' => $tRow['tz']];
$renamed = $api($edit, $owner);
platform_assert($renamed['data']['task']['enabled'] === true && !isset($renamed['data']['approval']), 'renaming keeps an approved task on, no card');
$changed = $api(['prompt' => 'Five headlines instead.'] + $edit, $owner);
platform_assert($changed['data']['task']['enabled'] === false && ($changed['data']['approval']['action'] ?? '') === 'task-start', 'changing the prompt pauses it and asks again');
$changeCard = $changed['data']['approval'];
$api(['hour' => 8] + ['prompt' => 'Five headlines instead.'] + $edit, $owner);
$api(['op' => 'decide', 'approval_id' => (int) $changeCard['id'], 'decision' => 'approve'], $owner);
$stale = $api(['op' => 'task-toggle', 'task_id' => $taskId, 'enabled' => true, 'approval_id' => (int) $changeCard['id']], $owner);
platform_assert($stale['status'] === 200 && $stale['data']['ok'] === false && str_contains($stale['data']['note'], 'changed after Yes') && (int) $db->query('SELECT enabled FROM tasks WHERE id = ' . $taskId)->fetchColumn() === 0,
    'a Yes for an older prompt/schedule does not start the edited task');
platform_assert($api(['op' => 'task-toggle', 'task_id' => $eveningId, 'enabled' => false], $owner)['status'] === 200, 'pausing needs no card');
platform_assert($api(['op' => 'task-toggle', 'task_id' => $eveningId, 'enabled' => true], $owner)['data']['approval']['action'] === 'task-start', 'task-toggle on asks first');

// ---- 4. run now: card, Yes runs exactly once ----
$before = $responses();
$rn = $api(['op' => 'task-run-now', 'task_id' => $eveningId], $owner);
platform_assert(($rn['data']['approval']['action'] ?? '') === 'task-start' && str_contains($rn['data']['approval']['title'], 'now') && $responses() === $before, 'run now is a card; no Grok call yet');
$api(['op' => 'decide', 'approval_id' => (int) $rn['data']['approval']['id'], 'decision' => 'approve'], $owner);
$ran = $api(['op' => 'task-run-now', 'task_id' => $eveningId, 'approval_id' => (int) $rn['data']['approval']['id']], $owner);
platform_assert($ran['status'] === 200 && ($ran['data']['run']['status'] ?? '') === 'delivered' && $responses() === $before + 1, 'Yes runs it once (one Grok call)');
$api(['op' => 'task-run-now', 'task_id' => $eveningId, 'approval_id' => (int) $rn['data']['approval']['id']], $owner);
$turn(['text' => 'x', 'approval_id' => (int) $rn['data']['approval']['id']], $owner);
platform_assert($responses() === $before + 1 + 1, 'a replay does not run it again (only the chat reply itself called Grok)');
platform_assert((int) $db->query('SELECT COUNT(*) FROM task_runs WHERE task_id = ' . $eveningId)->fetchColumn() === 1, 'exactly one task run recorded');

// ---- 5. expired cards cannot be approved ----
$old = $api(['op' => 'task-run-now', 'task_id' => $eveningId], $owner)['data']['approval'];
$db->exec('UPDATE approvals SET created_at = ' . (time() - 90000) . ' WHERE id = ' . (int) $old['id']);
$exp = $api(['op' => 'decide', 'approval_id' => (int) $old['id'], 'decision' => 'approve'], $owner);
platform_assert($exp['status'] === 410 && !empty($exp['data']['expired']) && $status((int) $old['id']) === 'pending', 'expired (24 h from created_at) cannot be approved: 410');
$listed = array_values(array_filter($api(['op' => 'approvals-pending'], $owner)['data']['approvals'], fn ($c) => (int) $c['id'] === (int) $old['id']));
platform_assert(($listed[0]['status'] ?? '') === 'expired', 'the reopened chat shows it as expired');

// ---- 6. approvals off: gated actions refuse, never run ungated ----
$offPrivate = platform_private('p0cardsoff', ['tasks' => true, 'approvals' => false], $common);
[$offProc, $offPipes] = platform_site($offPrivate, $site2);
$offUser = platform_signup($site2, 'cardsoff-' . getmypid() . '@simkosi.test');
$offSave = platform_api($site2, '/api/platform', ['op' => 'task-save'] + $base, $offUser['token']);
platform_assert($offSave['status'] === 200 && $offSave['data']['task']['enabled'] === false && !empty($offSave['data']['needs_approval']), 'approvals off: a task is saved paused');
platform_assert(platform_api($site2, '/api/platform', ['op' => 'task-run-now', 'task_id' => (int) $offSave['data']['task']['id']], $offUser['token'])['status'] === 403, 'approvals off: run now refuses');
platform_stop($offProc, $offPipes);

// ---- 7. paywall-on: owner only ----
platform_assert($api(['op' => 'paywall-set', 'on' => true], $other)['status'] === 403, 'a non-owner cannot ask for the paywall card');
$pw = $api(['op' => 'paywall-set', 'on' => true, 'session_id' => $chatA], $owner);
$pc = $pw['data']['approval'] ?? [];
platform_assert($pw['status'] === 200 && $pc['action'] === 'paywall-on' && $status((int) $pc['id']) === 'pending', 'owner gets a pending paywall-on card');
$facts = implode(' | ', $pc['facts']);
platform_assert(str_contains($facts, 'Price: $9.99/month') && str_contains($facts, 'Free messages: 5') && str_contains($facts, 'Stripe: test mode, account ending 9876')
    && str_contains($facts, 'Who: 1 non-owner account') && !str_contains(json_encode($pc), 'sk_test_localonly'), 'paywall card: price, 5 free, Stripe test + last 4 only, who: ' . $facts);
$otherSees = $api(['op' => 'approvals-pending'], $other)['data']['approvals'];
platform_assert(array_filter($otherSees, fn ($c) => $c['action'] === 'paywall-on') === [], 'a non-owner never sees a paywall-on card');
platform_assert($api(['op' => 'decide', 'approval_id' => (int) $pc['id'], 'decision' => 'approve'], $other)['status'] === 404, 'a non-owner cannot decide it');
$api(['op' => 'decide', 'approval_id' => (int) $pc['id'], 'decision' => 'decline'], $owner);
platform_assert($api(['op' => 'paywall-set', 'on' => true, 'approval_id' => (int) $pc['id']], $owner)['status'] === 403
    && $db->query("SELECT value FROM site_settings WHERE name = 'flag_paywall'")->fetchColumn() === false, 'No on the paywall card changes nothing');
$pt = $turn(['text' => 'PAYWALLON turn the paywall on please', 'session_id' => $chatA], $owner);
$pc2 = $pt['data']['approval'] ?? [];
platform_assert(($pc2['action'] ?? '') === 'paywall-on', 'the owner can ask Grok: turn_paywall_on becomes the card');
$ot = $turn(['text' => 'PAYWALLON turn the paywall on please'], $other);
platform_assert(!isset($ot['data']['approval']), 'Grok never offers the paywall tool to a non-owner');
$api(['op' => 'decide', 'approval_id' => (int) $pc2['id'], 'decision' => 'approve'], $owner);
$on = $turn(['text' => 'PAYWALLON turn the paywall on please', 'session_id' => $chatA, 'approval_id' => (int) $pc2['id']], $owner);
platform_assert(str_contains((string) ($on['data']['approval_result'] ?? ''), 'Paywall on: $9.99/month after 5 free messages (Stripe test)'), 'Yes turns the paywall on: ' . json_encode($on['data']));
platform_assert($db->query("SELECT value FROM site_settings WHERE name = 'flag_paywall'")->fetchColumn() === 'true', 'the flag is stored in site_settings');
platform_assert(($on['data']['usage'] ?? null) !== null, 'simko_flag(paywall) now reads the stored setting (usage shown)');
$turn(['text' => 'again', 'approval_id' => (int) $pc2['id']], $owner);
platform_assert($ranCount((int) $pc2['id']) === 1, 'paywall Yes runs once');
platform_assert($api(['op' => 'paywall-set', 'on' => false], $owner)['data']['paywall'] === false
    && $db->query("SELECT value FROM site_settings WHERE name = 'flag_paywall'")->fetchColumn() === 'false', 'the owner can turn it off again without a card');

// ---- 8. mcp-token-share: once per user per connector login ----
$srv = $api(['op' => 'mcp-save', 'label' => 'Locked notes', 'url' => 'http://127.0.0.1:' . $mcpPort . '/mcp-auth', 'bearer_token' => 'mcp-test-token'], $other);
$sid = (int) $srv['data']['server']['id'];
$chatB = $session($other);
$first = $turn(['text' => 'find my grout note', 'session_id' => $chatB], $other);
$tc = $first['data']['approvals'][0] ?? [];
platform_assert(($tc['action'] ?? '') === 'mcp-token-share' && $tc['title'] === 'Allow reading from Locked notes?'
    && str_contains($tc['what'], 'To read from Locked notes, Simko SI sends your Locked notes login to xAI, which makes the request for you.'), 'first use shows the token card');
platform_assert(!str_contains((string) $first['data']['everyday'], 'simko_s' . $sid), 'read tools are not offered before the answer');
$second = $turn(['text' => 'find my grout note', 'session_id' => $chatB], $other);
platform_assert(empty($second['data']['approvals']) && (int) $db->query("SELECT COUNT(*) FROM approvals WHERE action = 'mcp-token-share' ")->fetchColumn() === 1, 'the token card is shown once (no duplicate while waiting)');
$api(['op' => 'decide', 'approval_id' => (int) $tc['id'], 'decision' => 'decline'], $other);
$afterNo = $turn(['text' => 'find my grout note', 'session_id' => $chatB], $other);
platform_assert(!str_contains((string) $afterNo['data']['everyday'], 'simko_s' . $sid) && empty($afterNo['data']['approvals']), 'No: read tools are not offered, and it does not ask again');
platform_assert($api(['op' => 'mcp-tools', 'server_id' => $sid, 'tools' => ['create_note' => true]], $other)['status'] === 200, 'allow a write tool');
$w = $turn(['text' => 'MCPWRITE add a note to buy grout', 'session_id' => $chatB], $other);
platform_assert(($w['data']['approval']['action'] ?? '') === 'mcp-write', 'No keeps the connector connected: writes still go through our server after Yes');
platform_assert(count($api(['op' => 'mcp-list'], $other)['data']['servers']) === 1, 'still connected');
// A new login for the same connector asks again.
$code = 'require ' . var_export(dirname(__DIR__) . '/public_html/api/mcp.php', true) . '; [$n, $c] = simko_connector_seal("mcp-new-token", simko_connector_key());'
    . ' $s = simko_db()->prepare("UPDATE mcp_servers SET token_nonce = ?, token_cipher = ? WHERE id = ' . $sid . '"); $s->bindValue(1, $n, PDO::PARAM_LOB); $s->bindValue(2, $c, PDO::PARAM_LOB); $s->execute(); echo "SEALED";';
platform_assert(str_contains((string) shell_exec('SIMKOSI_PRIVATE=' . escapeshellarg($private) . ' php -r ' . escapeshellarg($code) . ' 2>&1'), 'SEALED'), 'token changed');
$again = $turn(['text' => 'find my grout note', 'session_id' => $chatB], $other);
$tc2 = $again['data']['approvals'][0] ?? [];
platform_assert(($tc2['action'] ?? '') === 'mcp-token-share' && (int) $tc2['id'] !== (int) $tc['id'], 'a changed token shows the card again');
$api(['op' => 'decide', 'approval_id' => (int) $tc2['id'], 'decision' => 'approve'], $other);
platform_assert((int) $db->query("SELECT COUNT(*) FROM audit_log WHERE summary = 'mcp-token-consent: Locked notes'")->fetchColumn() === 1, 'Yes is logged as mcp-token-consent: <server>');
$consented = $turn(['text' => 'find my grout note', 'session_id' => $chatB, 'approval_id' => (int) $tc2['id']], $other);
platform_assert(str_contains((string) $consented['data']['everyday'], 'simko_s' . $sid . '=get_note|search_notes+auth') && ($consented['data']['approval_result'] ?? '') === 'Locked notes read tools on', 'after Yes the read tools are offered: ' . ($consented['data']['everyday'] ?? ''));
$later = $turn(['text' => 'find my grout note', 'session_id' => $chatB], $other);
platform_assert(empty($later['data']['approvals']) && str_contains((string) $later['data']['everyday'], '+auth'), 'consent is remembered (card not shown again)');
platform_assert($toolCalls() === 0, 'nothing ran on the connector from these cards');
platform_stop($proc, $pipes);

// ---- 9. mcp-spend: paid connector calls (and one combined card for a paid write) ----
$paidPrivate = platform_private('p0cardspaid', $flags, $common + [
    'mcp' => ['allowed_hosts' => ['127.0.0.1'], 'allow_http' => true, 'allow_private' => true, 'paid_hosts' => ['127.0.0.1' => 0.05]],
]);
[$proc2, $pipes2] = platform_site($paidPrivate, $site3);
$payer = platform_signup($site3, 'cardspay-' . getmypid() . '@simkosi.test');
$papi = static fn (array $body) => platform_api($site3, '/api/platform', $body, $payer['token']);
$pturn = static fn (array $body) => platform_api($site3, '/api/simco/turn', $body, $payer['token']);
$pdb = new PDO('sqlite:' . $paidPrivate . '/data/simko.sqlite');
$ps = $papi(['op' => 'mcp-save', 'label' => 'Paid notes', 'url' => 'http://127.0.0.1:' . $mcpPort . '/mcp']);
platform_assert($ps["status"] === 200, "paid server saved: " . json_encode($ps));
$psid = (int) $ps['data']['server']['id'];
$plain = $pturn(['text' => 'hello there']);
platform_assert(!str_contains((string) $plain['data']['everyday'], '[mcp:'), 'paid server reads are not handed to the xAI mcp tool');
$r = $pturn(['text' => 'MCPREAD look for grout']);
$sc = $r['data']['approval'] ?? [];
platform_assert(($sc['action'] ?? '') === 'mcp-spend' && $sc['cost_usd'] === 0.05 && str_contains($sc['cost_label'], 'About $0.050 for this call') && $sc['facts'] === ['Costs money']
    && str_contains($sc['where'], 'Paid notes (127.0.0.1)'), 'a paid read becomes an mcp-spend card with cost and cap left: ' . json_encode($sc));
platform_assert($toolCalls() === 0, 'nothing runs before Yes');
$papi(['op' => 'decide', 'approval_id' => (int) $sc['id'], 'decision' => 'approve']);
$pd = $pturn(['text' => 'go', 'approval_id' => (int) $sc['id']]);
platform_assert($toolCalls() === 1 && str_contains((string) ($pd['data']['approval_result'] ?? ''), 'Paid notes · search_notes ($0.05)'), 'Yes runs the paid call once from our server: ' . json_encode($pd['data']));
$spent = (int) $pdb->query('SELECT COALESCE(SUM(ticks), 0) FROM xai_spend')->fetchColumn();
platform_assert($spent >= 500000000, 'the call cost counts toward today\'s cap');
$pturn(['text' => 'go', 'approval_id' => (int) $sc['id']]);
platform_assert($toolCalls() === 1, 'a second run of the same card does nothing');
$papi(['op' => 'mcp-tools', 'server_id' => $psid, 'tools' => ['create_note' => true]]);
$pw2 = $pturn(['text' => 'MCPWRITE add a note to buy grout']);
$combo = $pw2['data']['approval'] ?? [];
platform_assert(($combo['action'] ?? '') === 'mcp-spend' && $combo['facts'] === ['Changes something', 'Costs money'] && str_contains($combo['title'], 'Change something in Paid notes (paid): create_note')
    && (int) $pdb->query("SELECT COUNT(*) FROM approvals WHERE status = 'pending'")->fetchColumn() === 1, 'a paid write is one combined card: ' . json_encode($combo));
$papi(['op' => 'decide', 'approval_id' => (int) $combo['id'], 'decision' => 'decline']);
$pturn(['text' => 'go', 'approval_id' => (int) $combo['id']]);
platform_assert($toolCalls() === 1, 'No on a spend card runs nothing');
platform_stop($proc2, $pipes2);

// xAI tool fee above the threshold also gates reads (in-process, no server).
$feePrivate = platform_private('p0cardsfee', $flags, $common + ['mcp' => ['xai_tool_fee_usd' => 0.02, 'spend_threshold_usd' => 0.01]]);
$feeCode = 'require ' . var_export(dirname(__DIR__) . '/public_html/api/mcp.php', true) . '; $s = ["host" => "mcp.example.com"];'
    . ' echo json_encode([simko_mcp_call_cost($s, "read"), simko_mcp_call_cost($s, "write")]);';
platform_assert(trim((string) shell_exec('SIMKOSI_PRIVATE=' . escapeshellarg($feePrivate) . ' php -r ' . escapeshellarg($feeCode) . ' 2>&1')) === '[0.02,0]', 'an xAI tool fee above the threshold makes reads a spend card');
fwrite(STDOUT, "approval card tests passed\n");
