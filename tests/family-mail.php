<?php
declare(strict_types=1);

/**
 * SMTP, confirmation, reset, and parent/child scoping.
 * Uses a temporary private directory. Does not touch production.
 */

$root = dirname(__DIR__);
$private = sys_get_temp_dir() . '/simko-family-' . getmypid();
$certDir = $private . '/certs';
@mkdir($certDir, 0700, true);
@mkdir($private . '/data', 0700, true);
$cert = $certDir . '/cert.pem';
$key = $certDir . '/key.pem';
$capture = $private . '/smtp.jsonl';
passthru(
    'openssl req -x509 -newkey rsa:2048 -sha256 -keyout ' . escapeshellarg($key)
    . ' -out ' . escapeshellarg($cert)
    . ' -days 2 -nodes -subj /CN=127.0.0.1 2>/dev/null',
    $openssl
);
if ($openssl !== 0 || !is_file($cert)) {
    fwrite(STDERR, "openssl cert failed\n");
    exit(1);
}

function write_config(string $private, string $mode, int $port, string $encryption, string $mailMode): void
{
    $body = <<<PHP
<?php
declare(strict_types=1);
return [
    'xai_api_key' => 'xai-local-mock',
    'xai_base_url' => 'http://127.0.0.1:9/v1',
    'model' => 'grok-4.7',
    'mail_mode' => '{$mailMode}',
    'site_url' => 'https://simkosi.com',
    'family_ui' => false,
    'max_input_chars' => 8000,
    'smtp' => [
        'host' => '127.0.0.1',
        'port' => {$port},
        'encryption' => '{$encryption}',
        'user' => 'mailer@simkosi.test',
        'password' => 'test-secret',
        'from' => 'hello@simkosi.test',
        'from_name' => 'Simko SI',
        'verify_peer' => false,
    ],
];
PHP;
    file_put_contents($private . '/config.php', $body);
}

function start_smtp(int $port, string $mode, string $cert, string $key, string $capture): array
{
    @unlink($capture . '.ready');
    $cmd = 'php ' . escapeshellarg(__DIR__ . '/fake-smtp.php') . ' ' . $port . ' ' . $mode . ' '
        . escapeshellarg($cert) . ' ' . escapeshellarg($key) . ' ' . escapeshellarg($capture);
    $proc = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $pipes);
    $deadline = microtime(true) + 5;
    while (microtime(true) < $deadline && !is_file($capture . '.ready')) {
        usleep(50000);
    }
    if (!is_file($capture . '.ready')) {
        $err = stream_get_contents($pipes[2]);
        fwrite(STDERR, "smtp did not start: " . $err . "\n");
        exit(1);
    }
    return [$proc, $pipes];
}

function start_site(string $private, int $port): array
{
    $cmd = 'php -S 127.0.0.1:' . $port . ' -t ' . escapeshellarg($GLOBALS['root'] . '/public_html')
        . ' ' . escapeshellarg($GLOBALS['root'] . '/public_html/router.php');
    $env = getenv();
    if (!is_array($env)) {
        $env = [];
    }
    $env['SIMKOSI_PRIVATE'] = $private;
    $proc = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $pipes, $GLOBALS['root'], $env);
    $deadline = microtime(true) + 8;
    while (microtime(true) < $deadline) {
        $probe = @file_get_contents('http://127.0.0.1:' . $port . '/api/health');
        if (is_string($probe) && str_contains($probe, 'simko-si')) {
            return [$proc, $pipes];
        }
        usleep(80000);
    }
    fwrite(STDERR, "site did not start\n" . stream_get_contents($pipes[2]));
    exit(1);
}

function api(int $port, string $path, array $body, ?string $token = null): array
{
    if ($token) {
        $body['token'] = $token;
    }
    $ctx = stream_context_create([
        'http' => [
            'method' => 'POST',
            'header' => "Content-Type: application/json\r\nOrigin: http://127.0.0.1:{$port}\r\n",
            'content' => json_encode($body),
            'ignore_errors' => true,
            'timeout' => 20,
        ],
    ]);
    $raw = file_get_contents('http://127.0.0.1:' . $port . $path, false, $ctx);
    $status = 0;
    foreach ($http_response_header ?? [] as $header) {
        if (preg_match('#HTTP/\S+\s+(\d+)#', $header, $match)) {
            $status = (int) $match[1];
        }
    }
    $data = json_decode((string) $raw, true);
    return ['status' => $status, 'data' => is_array($data) ? $data : ['raw' => $raw]];
}

function captured(string $capture): array
{
    if (!is_file($capture)) {
        return [];
    }
    $rows = [];
    foreach (file($capture, FILE_IGNORE_NEW_LINES) ?: [] as $line) {
        $decoded = json_decode($line, true);
        if (is_array($decoded)) {
            $rows[] = $decoded;
        }
    }
    return $rows;
}

function assert_true(bool $ok, string $message): void
{
    if (!$ok) {
        fwrite(STDERR, "FAIL " . $message . "\n");
        exit(1);
    }
    fwrite(STDOUT, "ok " . $message . "\n");
}

function stop_proc($proc, array $pipes): void
{
    foreach ($pipes as $pipe) {
        if (is_resource($pipe)) {
            fclose($pipe);
        }
    }
    if (is_resource($proc)) {
        proc_terminate($proc);
        proc_close($proc);
    }
}

$sitePort = 8771;
write_config($private, 'starttls', 1587, 'starttls', 'smtp');
[$smtp, $smtpPipes] = start_smtp(1587, 'starttls', $cert, $key, $capture);
[$site, $sitePipes] = start_site($private, $sitePort);

$email = 'parent-' . getmypid() . '@simkosi.test';
$signup = api($sitePort, '/api/auth', [
    'op' => 'signup',
    'email' => $email,
    'password' => 'reef-turtle-8',
    'parent' => true,
    'consent' => true,
]);
assert_true($signup['status'] === 200 && ($signup['data']['ok'] ?? false) === true, 'parent signup');
assert_true(!isset($signup['data']['dev_token']), 'smtp signup hides the confirm code');
assert_true(($signup['data']['parent'] ?? false) === true, 'signup stored parent consent');
$mails = captured($capture);
assert_true(count($mails) === 1, 'one confirm email');
$message = $mails[0]['message'];
assert_true(str_contains($message, 'Simko SI'), 'sender name Simko SI');
assert_true(str_contains($message, 'text/plain') && str_contains($message, 'text/html'), 'plain and html bodies');
assert_true(str_contains($message, base64_encode('Confirm your Simko SI email')), 'confirm subject');
assert_true(str_contains($message, 'Confirm your email'), 'confirm html heading');
preg_match('/[a-f0-9]{32}/', $message, $code);
assert_true(!empty($code[0]), 'confirm code is in the email');
$tooSoon = api($sitePort, '/api/family', [
    'op' => 'create-child',
    'display_name' => 'Should Fail',
    'avatar' => 'turtle',
    'age_band' => 'Ages 7 to 9',
], $signup['data']['token']);
assert_true($tooSoon['status'] === 403, 'child profile waits for a confirmed parent email');
$confirm = api($sitePort, '/api/auth', ['op' => 'confirm-email', 'confirm_token' => $code[0]], $signup['data']['token']);
assert_true($confirm['status'] === 200 && ($confirm['data']['ok'] ?? false), 'confirm email code');

$noConsent = api($sitePort, '/api/auth', [
    'op' => 'signup',
    'email' => 'plain-' . getmypid() . '@simkosi.test',
    'password' => 'reef-turtle-8',
    'parent' => true,
    'consent' => false,
]);
assert_true($noConsent['status'] === 400, 'parent signup without consent is refused');

$adult = api($sitePort, '/api/auth', [
    'op' => 'signup',
    'email' => 'adult-' . getmypid() . '@simkosi.test',
    'password' => 'reef-turtle-8',
]);
assert_true($adult['status'] === 200, 'adult signup');
preg_match('/[a-f0-9]{32}/', captured($capture)[count(captured($capture)) - 1]['message'], $adultCode);
api($sitePort, '/api/auth', ['op' => 'confirm-email', 'confirm_token' => $adultCode[0]]);
$adultChild = api($sitePort, '/api/family', [
    'op' => 'create-child',
    'display_name' => 'Nope',
    'avatar' => 'turtle',
    'age_band' => 'Ages 7 to 9',
], $adult['data']['token']);
assert_true($adultChild['status'] === 403, 'no child profile without parent consent');

$pii = api($sitePort, '/api/family', [
    'op' => 'create-child',
    'display_name' => 'Lumen',
    'avatar' => 'turtle',
    'age_band' => 'Ages 7 to 9',
    'birthdate' => '2018-01-01',
    'last_name' => 'Secret',
], $signup['data']['token']);
assert_true($pii['status'] === 400, 'birthdate and last name are rejected');

$child = api($sitePort, '/api/family', [
    'op' => 'create-child',
    'display_name' => 'Lumen',
    'avatar' => 'turtle',
    'age_band' => 'Ages 7 to 9',
], $signup['data']['token']);
assert_true($child['status'] === 200 && ($child['data']['child']['display_name'] ?? '') === 'Lumen', 'parent creates a child');
$childId = (int) $child['data']['child']['id'];

$chat = api($sitePort, '/api/sessions', [
    'op' => 'create',
    'title' => 'Bedtime story',
    'child_id' => $childId,
], $signup['data']['token']);
assert_true($chat['status'] === 200, 'child chat created');
$chatId = (string) $chat['data']['session']['id'];

$ownList = api($sitePort, '/api/sessions', ['op' => 'list'], $signup['data']['token']);
$titles = array_column($ownList['data']['sessions'] ?? [], 'title');
assert_true(!in_array('Bedtime story', $titles, true), 'parent list hides child chats until a child is chosen');
$childList = api($sitePort, '/api/sessions', ['op' => 'list', 'child_id' => $childId], $signup['data']['token']);
assert_true(($childList['data']['sessions'][0]['title'] ?? '') === 'Bedtime story', 'child list shows that child only');

$other = api($sitePort, '/api/auth', [
    'op' => 'signup',
    'email' => 'other-' . getmypid() . '@simkosi.test',
    'password' => 'reef-turtle-8',
    'parent' => true,
    'consent' => true,
]);
preg_match('/[a-f0-9]{32}/', captured($capture)[count(captured($capture)) - 1]['message'], $otherCode);
api($sitePort, '/api/auth', ['op' => 'confirm-email', 'confirm_token' => $otherCode[0]]);
$peek = api($sitePort, '/api/family', ['op' => 'status'], $other['data']['token']);
assert_true(($peek['data']['children'] ?? null) === [], 'other parent sees no children');
$steal = api($sitePort, '/api/sessions', ['op' => 'list', 'child_id' => $childId], $other['data']['token']);
assert_true($steal['status'] === 404, 'other family cannot list this child');
$stealChat = api($sitePort, '/api/sessions', ['op' => 'get', 'session_id' => $chatId], $other['data']['token']);
assert_true($stealChat['status'] === 404, 'other family cannot open the chat');
$stealDelete = api($sitePort, '/api/family', ['op' => 'delete-chat', 'session_id' => $chatId], $other['data']['token']);
assert_true($stealDelete['status'] === 404, 'other family cannot delete the chat');
$removed = api($sitePort, '/api/family', ['op' => 'delete-chat', 'session_id' => $chatId], $signup['data']['token']);
assert_true($removed['status'] === 200, 'parent deletes the child chat');

$reset = api($sitePort, '/api/auth', ['op' => 'request-reset', 'email' => $email]);
assert_true($reset['status'] === 200 && !isset($reset['data']['dev_token']), 'reset email hides the code');
$resetMail = captured($capture)[count(captured($capture)) - 1]['message'];
assert_true(str_contains($resetMail, base64_encode('Reset your Simko SI password')), 'reset subject');
assert_true(str_contains($resetMail, 'Reset your password'), 'reset html heading');
preg_match('/[a-f0-9]{32}/', $resetMail, $resetCode);
$changed = api($sitePort, '/api/auth', [
    'op' => 'reset-password',
    'reset_token' => $resetCode[0],
    'password' => 'reef-turtle-9',
]);
assert_true($changed['status'] === 200, 'password reset from the email code');
$signed = api($sitePort, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'reef-turtle-9']);
assert_true($signed['status'] === 200, 'sign in with the new password');

$forParent = static function () use ($capture, $email): int {
    $count = 0;
    foreach (captured($capture) as $row) {
        if (str_contains(strtolower((string) ($row['to'] ?? '')), strtolower($email))) {
            $count++;
        }
    }
    return $count;
};
$guard = 0;
while ($forParent() < 5 && $guard < 8) {
    $again = api($sitePort, '/api/auth', ['op' => 'request-reset', 'email' => $email]);
    assert_true($again['status'] === 200, 'reset still allowed at ' . $forParent());
    $guard++;
}
assert_true($forParent() === 5, 'five emails recorded for the parent address');
$blocked = api($sitePort, '/api/auth', ['op' => 'request-reset', 'email' => $email]);
assert_true($blocked['status'] === 429, 'sixth email in an hour is refused');

stop_proc($site, $sitePipes);
stop_proc($smtp, $smtpPipes);

$sslCapture = $private . '/ssl.jsonl';
write_config($private, 'ssl', 1465, 'ssl', 'smtp');
[$ssl, $sslPipes] = start_smtp(1465, 'ssl', $cert, $key, $sslCapture);
[$site2, $site2Pipes] = start_site($private, $sitePort);
$sslSignup = api($sitePort, '/api/auth', [
    'op' => 'signup',
    'email' => 'ssl-' . getmypid() . '@simkosi.test',
    'password' => 'reef-turtle-8',
]);
assert_true($sslSignup['status'] === 200, 'signup over SSL smtp');
$sslMail = captured($sslCapture);
assert_true(count($sslMail) === 1 && ($sslMail[0]['mode'] ?? '') === 'ssl', 'SSL capture');
assert_true(str_contains($sslMail[0]['message'], 'Simko SI'), 'SSL mail is from Simko SI');
stop_proc($site2, $site2Pipes);
stop_proc($ssl, $sslPipes);

$devPrivate = $private . '-dev';
@mkdir($devPrivate . '/data', 0700, true);
write_config($devPrivate, 'starttls', 1587, 'starttls', 'dev');
[$devSite, $devPipes] = start_site($devPrivate, 8772);
$dev = api(8772, '/api/auth', [
    'op' => 'signup',
    'email' => 'dev-' . getmypid() . '@simkosi.test',
    'password' => 'reef-turtle-8',
]);
assert_true($dev['status'] === 200 && isset($dev['data']['dev_token']), 'dev mode still returns the confirm code');
stop_proc($devSite, $devPipes);

fwrite(STDOUT, "family and mail tests passed\n");
