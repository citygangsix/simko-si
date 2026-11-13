<?php
declare(strict_types=1);

$GLOBALS['simko_root'] = dirname(__DIR__);
$GLOBALS['platform_procs'] = [];

function platform_private(string $name, array $flags, array $extra = []): string
{
    $dir = sys_get_temp_dir() . '/simko-' . $name . '-' . getmypid();
    @mkdir($dir . '/data', 0700, true);
    $config = array_merge([
        'xai_api_key' => 'xai-local-mock',
        'xai_base_url' => 'http://127.0.0.1:8799/v1',
        'model' => 'grok-4.7',
        'mail_mode' => 'dev',
        'site_url' => 'https://simkosi.com',
        'family_ui' => false,
        'max_input_chars' => 8000,
        'platform' => $flags,
        'square' => [
            'environment' => 'sandbox',
            'application_id' => '',
            'location_id' => '',
            'access_token' => '',
            'api_base' => 'https://connect.squareupsandbox.com',
        ],
    ], $extra);
    $export = var_export($config, true);
    file_put_contents($dir . '/config.php', "<?php\ndeclare(strict_types=1);\nreturn {$export};\n");
    return $dir;
}

function platform_site(string $private, int $port, string $mock = ''): array
{
    $cmd = 'php -S 127.0.0.1:' . $port . ' -t ' . escapeshellarg($GLOBALS['simko_root'] . '/public_html')
        . ' ' . escapeshellarg($GLOBALS['simko_root'] . '/public_html/router.php');
    $env = getenv();
    if (!is_array($env)) {
        $env = [];
    }
    $env['SIMKOSI_PRIVATE'] = $private;
    $proc = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $pipes, $GLOBALS['simko_root'], $env);
    $deadline = microtime(true) + 8;
    while (microtime(true) < $deadline) {
        $probe = @file_get_contents('http://127.0.0.1:' . $port . '/api/health');
        if (is_string($probe) && str_contains($probe, 'simko-si')) {
            platform_track($proc, $pipes);
            return [$proc, $pipes];
        }
        usleep(60000);
    }
    fwrite(STDERR, "site {$port} failed\n" . stream_get_contents($pipes[2]));
    exit(1);
}

function platform_mock(int $port): array
{
    $cmd = 'php -S 127.0.0.1:' . $port . ' -t ' . escapeshellarg($GLOBALS['simko_root'] . '/tests')
        . ' ' . escapeshellarg($GLOBALS['simko_root'] . '/tests/mock-xai.php');
    $proc = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $pipes, $GLOBALS['simko_root']);
    $deadline = microtime(true) + 8;
    while (microtime(true) < $deadline) {
        $ctx = stream_context_create(['http' => ['method' => 'POST', 'header' => "Content-Type: application/json\r\n", 'content' => '{"messages":[{"role":"user","content":"ping"}]}', 'ignore_errors' => true, 'timeout' => 2]]);
        $probe = @file_get_contents('http://127.0.0.1:' . $port . '/v1/chat/completions', false, $ctx);
        if (is_string($probe) && str_contains($probe, 'reef')) {
            platform_track($proc, $pipes);
            return [$proc, $pipes];
        }
        usleep(60000);
    }
    fwrite(STDERR, "mock {$port} failed\n");
    exit(1);
}

function platform_api(int $port, string $path, array $body, ?string $token = null): array
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
    return ['status' => $status, 'data' => is_array($data) ? $data : ['raw' => (string) $raw]];
}

function platform_assert(bool $ok, string $message): void
{
    if (!$ok) {
        fwrite(STDERR, "FAIL {$message}\n");
        exit(1);
    }
    fwrite(STDOUT, "ok {$message}\n");
}

function platform_stop($proc, array $pipes, int $pid = 0): void
{
    if ($pid < 1 && is_resource($proc)) {
        $status = proc_get_status($proc);
        $pid = (int) ($status['pid'] ?? 0);
    }
    foreach ($pipes as $pipe) {
        if (is_resource($pipe)) {
            fclose($pipe);
        }
    }
    if ($pid > 1 && function_exists('posix_kill')) {
        @posix_kill($pid, SIGTERM);
    }
    if (is_resource($proc)) {
        proc_terminate($proc, SIGTERM);
        $deadline = microtime(true) + 1;
        while (is_resource($proc) && microtime(true) < $deadline) {
            $status = proc_get_status($proc);
            if (empty($status['running'])) {
                break;
            }
            usleep(20000);
        }
        if ($pid > 1 && function_exists('posix_kill')) {
            @posix_kill($pid, SIGKILL);
        }
        proc_close($proc);
    } elseif ($pid > 1 && function_exists('posix_kill')) {
        @posix_kill($pid, SIGKILL);
    }
}

function platform_track($proc, array $pipes): void
{
    $pid = 0;
    if (is_resource($proc)) {
        $status = proc_get_status($proc);
        $pid = (int) ($status['pid'] ?? 0);
    }
    $GLOBALS['platform_procs'][] = [$proc, $pipes, $pid];
}


function platform_signup(int $port, string $email): array
{
    $signup = platform_api($port, '/api/auth', [
        'op' => 'signup',
        'email' => $email,
        'password' => 'reef-turtle-8',
    ]);
    platform_assert($signup['status'] === 200 && !empty($signup['data']['token']), 'signup ' . $email);
    if (!empty($signup['data']['dev_token'])) {
        platform_api($port, '/api/auth', ['op' => 'confirm-email', 'confirm_token' => $signup['data']['dev_token']]);
    }
    return $signup['data'];
}

function platform_post_raw(int $port, string $path, string $body, array $headers = []): array
{
    $headerLines = "Content-Type: application/json\r\n";
    foreach ($headers as $name => $value) {
        $headerLines .= $name . ': ' . $value . "\r\n";
    }
    $ctx = stream_context_create([
        'http' => [
            'method' => 'POST',
            'header' => $headerLines,
            'content' => $body,
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
    return ['status' => $status, 'data' => is_array($data) ? $data : ['raw' => (string) $raw]];
}

function platform_stripe_mock(int $port, string $capturePath): array
{
    $cmd = 'php -S 127.0.0.1:' . $port . ' -t ' . escapeshellarg($GLOBALS['simko_root'] . '/tests')
        . ' ' . escapeshellarg($GLOBALS['simko_root'] . '/tests/mock-stripe.php');
    $env = getenv();
    if (!is_array($env)) {
        $env = [];
    }
    $env['SIMKO_STRIPE_CAPTURE'] = $capturePath;
    $proc = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $pipes, $GLOBALS['simko_root'], $env);
    $deadline = microtime(true) + 8;
    while (microtime(true) < $deadline) {
        $ctx = stream_context_create([
            'http' => [
                'method' => 'POST',
                'header' => "Content-Type: application/x-www-form-urlencoded\r\n",
                'content' => 'mode=subscription',
                'ignore_errors' => true,
                'timeout' => 2,
            ],
        ]);
        $probe = @file_get_contents('http://127.0.0.1:' . $port . '/v1/checkout/sessions', false, $ctx);
        if (is_string($probe) && str_contains($probe, 'cs_test_mock_session')) {
            platform_track($proc, $pipes);
            return [$proc, $pipes];
        }
        usleep(60000);
    }
    fwrite(STDERR, "stripe mock {$port} failed\n");
    exit(1);
}

function platform_stripe_sign(string $payload, string $secret, ?int $timestamp = null): string
{
    $timestamp = $timestamp ?? time();
    $sig = hash_hmac('sha256', $timestamp . '.' . $payload, $secret);
    return 't=' . $timestamp . ',v1=' . $sig;
}


register_shutdown_function(static function (): void {
    foreach (array_reverse($GLOBALS['platform_procs'] ?? []) as $item) {
        platform_stop($item[0], $item[1], (int) ($item[2] ?? 0));
    }
    $GLOBALS['platform_procs'] = [];
});
