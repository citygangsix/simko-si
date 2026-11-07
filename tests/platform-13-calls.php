<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 9002;
$private = platform_private('calls', ['calls' => true, 'paywall' => false], [
    'calls' => ['provider' => '', 'from_number' => '', 'enabled' => false],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'call-' . getmypid() . '@simkosi.test');
$status = platform_api($sitePort, '/api/platform', ['op' => 'call-status'], $user['token']);
platform_assert($status['status'] === 200 && ($status['data']['enabled'] ?? true) === false, 'calls stay disabled');
platform_assert(str_contains((string) ($status['data']['reason'] ?? ''), 'per minute'), 'the screen says calls cost money');
platform_assert(array_key_exists('provider', $status['data']) && $status['data']['provider'] === null, 'no provider account is configured');

platform_stop($site, $sitePipes);
fwrite(STDOUT, "call tests passed\n");
