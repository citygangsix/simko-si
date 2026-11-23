<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Store readiness and account tools: download my data, report a reply, delete account,
// privacy-friendly telemetry.
$private = platform_private('account', ['paywall' => false]);
[$site, $pipes] = platform_site($private, 8874);
$email = 'acct-' . getmypid() . '@simkosi.test';
$u = platform_signup(8874, $email);
$other = platform_signup(8874, 'acct2-' . getmypid() . '@simkosi.test');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$uid = (int) $db->query('SELECT id FROM users WHERE email = ' . $db->quote($email))->fetchColumn();
$db->prepare('INSERT INTO chats (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)')->execute(['c-' . getmypid(), $uid, 'Reef chat', time(), time()]);
$db->prepare('INSERT INTO messages (chat_id, role, body, created_at) VALUES (?, ?, ?, ?)')->execute(['c-' . getmypid(), 'user', 'hello reef', time()]);
$db = null;

$exp = platform_api(8874, '/api/auth', ['op' => 'export-data'], $u['token']);
platform_assert($exp['status'] === 200 && ($exp['data']['export']['account']['email'] ?? '') === $email, 'export has the account');
platform_assert(($exp['data']['export']['chats'][0]['messages'][0]['body'] ?? '') === 'hello reef', 'export has chats with messages');
$json = json_encode($exp['data']);
platform_assert(!str_contains($json, 'password') && !str_contains($json, 'token_hash'), 'export has no password hash or tokens');
$anon = platform_api(8874, '/api/auth', ['op' => 'export-data']);
platform_assert($anon['status'] === 401, 'export needs sign-in');

$rep = platform_api(8874, '/api/report', ['reason' => 'false', 'note' => 'wrong date', 'reply' => 'The reef opened in 1802.'], $u['token']);
platform_assert($rep['status'] === 200, 'a reply can be reported');

$pv = platform_api(8874, '/api/telemetry', ['op' => 'pv', 'path' => '/help.html']);
platform_assert($pv['status'] === 204, 'page view counted');
$err = platform_api(8874, '/api/telemetry', ['op' => 'err', 'path' => '/', 'msg' => 'TypeError: x is undefined', 'src' => 'https://simkosi.com/assets/simco-app.js?v=1', 'line' => 12]);
platform_assert($err['status'] === 204, 'browser error recorded');
$sum = platform_api(8874, '/api/telemetry', ['op' => 'summary'], $u['token']);
platform_assert($sum['status'] === 200 && ($sum['data']['top_paths_30d'][0]['path'] ?? '') === '/help.html', 'owner summary lists page views');
platform_assert(($sum['data']['recent_errors'][0]['msg'] ?? '') === 'TypeError: x is undefined', 'owner summary lists errors');
$log = (string) @file_get_contents($private . '/data/client-errors.log');
platform_assert(!str_contains($log, '127.0.0.1') && !str_contains($log, 'simkosi.com/assets'), 'error log keeps no IP and no host');

$bad = platform_api(8874, '/api/auth', ['op' => 'delete-account', 'confirm' => 'nope'], $u['token']);
platform_assert($bad['status'] === 400, 'delete needs DELETE typed');
$del = platform_api(8874, '/api/auth', ['op' => 'delete-account', 'confirm' => 'DELETE'], $u['token']);
platform_assert($del['status'] === 200 && ($del['data']['deleted'] ?? false), 'account deleted');
$me = platform_api(8874, '/api/auth', ['op' => 'me'], $u['token']);
platform_assert($me['status'] !== 200 || empty($me['data']['email']), 'deleted account token no longer works');
$signin = platform_api(8874, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'reef-turtle-8']);
platform_assert($signin['status'] === 401, 'deleted account cannot sign in');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
platform_assert((int) $db->query("SELECT COUNT(*) FROM messages WHERE chat_id = 'c-" . getmypid() . "'")->fetchColumn() === 0, 'chats and messages are gone');
$otherMe = platform_api(8874, '/api/auth', ['op' => 'me'], $other['token']);
platform_assert($otherMe['status'] === 200, 'other accounts are untouched');
platform_stop($site, $pipes);
fwrite(STDOUT, "account tests passed\n");
