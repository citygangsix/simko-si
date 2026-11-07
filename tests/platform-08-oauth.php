<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 8912;
$oidcPort = 8913;
$private = platform_private('oauth-off', ['oauth' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$hidden = platform_api($sitePort, '/api/platform', ['op' => 'oauth-start', 'provider' => 'google']);
platform_assert($hidden['status'] === 404, 'Google stays hidden when the client id is empty');
$health = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/health');
platform_assert(is_string($health) && str_contains($health, '"google":false') && str_contains($health, '"apple":false'), 'both buttons report hidden');
platform_stop($site, $sitePipes);

$cmd = 'php -S 127.0.0.1:' . $oidcPort . ' -t ' . escapeshellarg(dirname(__DIR__) . '/tests') . ' ' . escapeshellarg(dirname(__DIR__) . '/tests/fake-oidc.php');
$oidc = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $oidcPipes);
$ready = platform_private('oauth-on', ['oauth' => true], [
    'oauth' => [
        'google' => [
            'client_id' => 'google-client',
            'client_secret' => 'google-secret',
            'authorize_url' => 'http://127.0.0.1:' . $oidcPort . '/auth',
            'token_url' => 'http://127.0.0.1:' . $oidcPort . '/token',
            'userinfo_url' => 'http://127.0.0.1:' . $oidcPort . '/userinfo',
            'redirect_url' => 'http://127.0.0.1:8914/api/oauth/callback',
            'scope' => 'openid email',
        ],
        'apple' => [
            'client_id' => '',
            'client_secret' => '',
            'authorize_url' => 'https://appleid.apple.com/auth/authorize',
            'token_url' => 'https://appleid.apple.com/auth/token',
            'userinfo_url' => '',
            'redirect_url' => 'https://simkosi.com/api/oauth/callback',
            'scope' => 'name email',
        ],
    ],
]);
$sitePort = 8914;
[$site2, $site2Pipes] = platform_site($ready, $sitePort);
$start = platform_api($sitePort, '/api/platform', ['op' => 'oauth-start', 'provider' => 'google']);
platform_assert($start['status'] === 200 && str_contains((string) ($start['data']['url'] ?? ''), 'client_id=google-client'), 'Google authorize URL is built');
$state = (string) $start['data']['state'];
$deadline = microtime(true) + 5;
while (microtime(true) < $deadline) {
    $probe = @file_get_contents('http://127.0.0.1:' . $oidcPort . '/token', false, stream_context_create([
        'http' => ['method' => 'POST', 'ignore_errors' => true, 'timeout' => 1, 'content' => ''],
    ]));
    if (is_string($probe) && str_contains($probe, 'access_token')) {
        break;
    }
    usleep(50000);
}
$ctx = stream_context_create(['http' => ['ignore_errors' => true]]);
$html = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/oauth/callback?provider=google&code=abc&state=' . $state, false, $ctx);
platform_assert(is_string($html) && str_contains($html, 'ada@simkosi.test'), 'the code exchange signs the person in');
$apple = platform_api($sitePort, '/api/platform', ['op' => 'oauth-start', 'provider' => 'apple']);
platform_assert($apple['status'] === 404, 'Apple stays hidden without a Services ID');

platform_stop($site2, $site2Pipes);
platform_stop($oidc, $oidcPipes);
fwrite(STDOUT, "oauth tests passed\n");
