<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$fixturePort = 9033;
$sitePort = 9032;
$cmd = 'php -S 127.0.0.1:' . $fixturePort . ' ' . escapeshellarg(dirname(__DIR__) . '/tests/browse-fixture.php');
$fixture = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $fixturePipes, dirname(__DIR__));
$private = platform_private('browse', ['browse' => true, 'paywall' => false], [
    'browse_allow' => ['127.0.0.1'],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'browse-' . getmypid() . '@simkosi.test');
$page = platform_api($sitePort, '/api/platform', [
    'op' => 'browse',
    'url' => 'http://127.0.0.1:' . $fixturePort . '/',
], $user['token']);
platform_assert($page['status'] === 200 && str_contains((string) ($page['data']['text'] ?? ''), 'turtle came home'), 'an allow-listed page is read');
platform_assert(str_contains((string) ($page['data']['note'] ?? ''), 'shared hosting'), 'the limit of shared hosting is named');
$blocked = platform_api($sitePort, '/api/platform', ['op' => 'browse', 'url' => 'https://example.com/'], $user['token']);
platform_assert($blocked['status'] === 403, 'a host that is not allow-listed is refused');
$login = platform_api($sitePort, '/api/platform', ['op' => 'browse', 'url' => 'http://127.0.0.1:' . $fixturePort . '/login'], $user['token']);
platform_assert($login['status'] === 403, 'a login page is refused');

platform_stop($site, $sitePipes);
platform_stop($fixture, $fixturePipes);
fwrite(STDOUT, "browse tests passed\n");
