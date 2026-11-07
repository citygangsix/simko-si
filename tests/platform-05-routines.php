<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$sitePort = 8852;
$private = platform_private('routines', ['routines' => true, 'paywall' => false]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'routine-' . getmypid() . '@simkosi.test');
$now = time();
$saved = platform_api($sitePort, '/api/platform', [
    'op' => 'save-routine',
    'kind' => 'bedtime',
    'hour' => (int) date('G', $now),
    'minute' => 0,
], $user['token']);
platform_assert($saved['status'] === 200 && ($saved['data']['routine']['kind'] ?? '') === 'bedtime', 'bedtime routine is saved');
$worker = dirname(__DIR__) . '/public_html/api/routines-worker.php';
$cmd = 'SIMKOSI_PRIVATE=' . escapeshellarg($private) . ' php ' . escapeshellarg($worker);
exec($cmd . ' 2>&1', $out, $code);
platform_assert($code === 0 && str_contains(implode("\n", $out), 'delivered 1'), 'cron worker delivers the due routine: ' . implode(' | ', $out));
$list = platform_api($sitePort, '/api/platform', ['op' => 'routines'], $user['token']);
platform_assert(str_contains((string) ($list['data']['deliveries'][0]['body'] ?? ''), 'bedtime story'), 'the note is in the app');
exec($cmd, $out2, $code2);
platform_assert($code2 === 0 && str_contains(implode("\n", $out2), 'delivered 0'), 'the same routine does not send twice in a day');

platform_stop($site, $sitePipes);
fwrite(STDOUT, "routine tests passed\n");
