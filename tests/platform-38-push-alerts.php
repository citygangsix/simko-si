<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Routine push alerts: VAPID-signed, RFC 8291-encrypted Web Push to a fake push service that decrypts it.
$pushPort = 9113;
$sitePort = 9112;
platform_require_free_port($pushPort);
$b64u = static fn (string $r): string => rtrim(strtr(base64_encode($r), '+/', '-_'), '=');
$point = static function ($k): string {
    $d = openssl_pkey_get_details($k);
    return "\x04" . str_pad($d['ec']['x'], 32, "\0", STR_PAD_LEFT) . str_pad($d['ec']['y'], 32, "\0", STR_PAD_LEFT);
};
$vapid = openssl_pkey_new(['curve_name' => 'prime256v1', 'private_key_type' => OPENSSL_KEYTYPE_EC]);
openssl_pkey_export($vapid, $vapidPem);
$vapidPub = $b64u($point($vapid));
$ua = openssl_pkey_new(['curve_name' => 'prime256v1', 'private_key_type' => OPENSSL_KEYTYPE_EC]);
openssl_pkey_export($ua, $uaPem);
$uaAuth = $b64u(random_bytes(16));
$log = sys_get_temp_dir() . '/simko-push-log-' . getmypid() . '.txt';
@unlink($log);
$env = (getenv() ?: []) + [];
$env['SIMKO_PUSH_LOG'] = $log;
$env['SIMKO_VAPID_PUB'] = $vapidPub;
$env['SIMKO_UA_PEM'] = $uaPem;
$env['SIMKO_UA_AUTH'] = $uaAuth;
$fake = proc_open('php -S 127.0.0.1:' . $pushPort . ' ' . escapeshellarg(__DIR__ . '/fake-push.php'), [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $fakePipes, __DIR__, $env);
platform_track($fake, $fakePipes);
platform_wait_port($pushPort);

// Without keys: alerts are hidden.
$bare = platform_private('push-bare', ['routines' => true]);
[$s0, $p0] = platform_site($bare, $sitePort + 2);
$z = platform_signup($sitePort + 2, 'push-z-' . getmypid() . '@simkosi.test');
$st = platform_api($sitePort + 2, '/api/platform', ['op' => 'push-status'], $z['token']);
platform_assert($st['status'] === 200 && $st['data']['available'] === false && $st['data']['public_key'] === '', 'no VAPID keys: alerts are not offered');
platform_stop($s0, $p0);

$private = platform_private('push-alerts', ['routines' => true], [
    'push' => ['vapid_public_key' => $vapidPub, 'vapid_private_pem' => $vapidPem, 'subject' => 'mailto:noreply@simkosi.com', 'extra_hosts' => ['127.0.0.1:' . $pushPort]],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$u = platform_signup($sitePort, 'push-' . getmypid() . '@simkosi.test');
$v = platform_signup($sitePort, 'push-v-' . getmypid() . '@simkosi.test');
platform_assert(platform_api($sitePort, '/api/platform', ['op' => 'push-status'])['status'] === 401, 'alerts need sign-in');
$st = platform_api($sitePort, '/api/platform', ['op' => 'push-status'], $u['token']);
platform_assert($st['data']['available'] === true && $st['data']['public_key'] === $vapidPub && $st['data']['routine_alerts'] === false && $st['data']['devices'] === 0, 'status gives the public key only, alerts start off');
platform_assert(!str_contains($st['raw'] ?? json_encode($st['data']), 'PRIVATE'), 'the private key never leaves the server');

$sub = ['endpoint' => 'http://127.0.0.1:' . $pushPort . '/push/device-one', 'keys' => ['p256dh' => $b64u($point($ua)), 'auth' => $uaAuth]];
$bad = platform_api($sitePort, '/api/platform', ['op' => 'push-subscribe', 'subscription' => ['endpoint' => 'https://evil.example.com/push', 'keys' => $sub['keys']]], $u['token']);
platform_assert($bad['status'] === 400, 'an endpoint that is not a browser push service is refused');
$bad2 = platform_api($sitePort, '/api/platform', ['op' => 'push-subscribe', 'subscription' => ['endpoint' => $sub['endpoint'], 'keys' => ['p256dh' => 'abc', 'auth' => $uaAuth]]], $u['token']);
platform_assert($bad2['status'] === 400, 'a broken browser key is refused');
platform_assert(platform_api($sitePort, '/api/platform', ['op' => 'push-test'], $u['token'])['status'] === 400, 'test alert needs a device first');

$on = platform_api($sitePort, '/api/platform', ['op' => 'push-subscribe', 'subscription' => $sub, 'routine_alerts' => true], $u['token']);
platform_assert($on['status'] === 200 && $on['data']['routine_alerts'] === true && $on['data']['devices'] === 1, 'subscribing turns routine alerts on');
$again = platform_api($sitePort, '/api/platform', ['op' => 'push-subscribe', 'subscription' => $sub], $u['token']);
platform_assert($again['data']['devices'] === 1, 'subscribing twice keeps one device');

$test = platform_api($sitePort, '/api/platform', ['op' => 'push-test'], $u['token']);
platform_assert($test['status'] === 200 && $test['data']['sent'] === 1 && $test['data']['failed'] === 0, 'test alert is accepted by the push service');
$lines = array_map(static fn ($l) => json_decode($l, true), file($log, FILE_IGNORE_NEW_LINES) ?: []);
$last = end($lines);
platform_assert($last['jwt_ok'] === true, 'the VAPID JWT verifies against the public key with the right audience');
platform_assert($last['encoding'] === 'aes128gcm' && $last['ttl'] !== '', 'aes128gcm and TTL headers are sent');
platform_assert(($last['payload']['title'] ?? '') === 'Simko SI' && str_contains((string) ($last['payload']['body'] ?? ''), 'Test alert'), 'the browser can decrypt the test alert');
platform_assert(platform_api($sitePort, '/api/platform', ['op' => 'push-test'], $v['token'])['status'] === 400, 'another person has no devices of mine');

// A routine run sends an alert.
$r = platform_api($sitePort, '/api/platform', ['op' => 'save-routine', 'kind' => 'homework', 'hour' => (int) gmdate('G'), 'minute' => (int) gmdate('i'), 'tz' => 'UTC'], $u['token']);
platform_assert($r['status'] === 200, 'routine saved');
$before = count($lines);
$run = static function () use ($private): string {
    $code = 'require ' . var_export(dirname(__DIR__) . '/public_html/api/routines.php', true) . '; echo simko_routines_run(time() + 60);';
    return (string) shell_exec('SIMKOSI_PRIVATE=' . escapeshellarg($private) . ' php -r ' . escapeshellarg($code) . ' 2>&1');
};
$ran = $run();
platform_assert(trim($ran) !== '' && (int) $ran >= 1, 'the routine worker ran the routine: ' . $ran);
$lines = array_map(static fn ($l) => json_decode($l, true), file($log, FILE_IGNORE_NEW_LINES) ?: []);
platform_assert(count($lines) === $before + 1, 'one alert per routine run');
$last = end($lines);
platform_assert($last['jwt_ok'] === true && ($last['payload']['title'] ?? '') === 'Simko SI routine' && ($last['payload']['body'] ?? '') !== '', 'the routine alert decrypts with its note');

// Off means off.
$off = platform_api($sitePort, '/api/platform', ['op' => 'push-pref', 'routine_alerts' => false], $u['token']);
platform_assert($off['data']['routine_alerts'] === false, 'alerts can be turned off');
$code = 'require ' . var_export(dirname(__DIR__) . '/public_html/api/push.php', true) . '; $id = (int) simko_db()->query("SELECT id FROM users WHERE email LIKE \'push-%\' AND email NOT LIKE \'push-v-%\' AND email NOT LIKE \'push-z-%\'")->fetchColumn(); simko_push_routine($id, "hello"); echo "done";';
$o = (string) shell_exec('SIMKOSI_PRIVATE=' . escapeshellarg($private) . ' php -r ' . escapeshellarg($code) . ' 2>&1');
platform_assert(trim($o) === 'done', 'routine hook runs quietly: ' . $o);
$lines2 = file($log, FILE_IGNORE_NEW_LINES) ?: [];
platform_assert(count($lines2) === count($lines), 'no alert when routine alerts are off');

// A dead subscription (410) is dropped.
$gone = ['endpoint' => 'http://127.0.0.1:' . $pushPort . '/push/gone', 'keys' => $sub['keys']];
platform_api($sitePort, '/api/platform', ['op' => 'push-subscribe', 'subscription' => $gone], $v['token']);
$t2 = platform_api($sitePort, '/api/platform', ['op' => 'push-test'], $v['token']);
platform_assert($t2['data']['failed'] === 1 && $t2['data']['devices'] === 0, 'a gone subscription is removed');

$un = platform_api($sitePort, '/api/platform', ['op' => 'push-unsubscribe', 'endpoint' => $sub['endpoint']], $u['token']);
platform_assert($un['data']['devices'] === 0, 'unsubscribe removes the device');

// Service worker shows pushes; page has the toggle and button.
$sw = (string) file_get_contents(dirname(__DIR__) . '/public_html/sw.js');
platform_assert(str_contains($sw, "addEventListener('push'") && str_contains($sw, 'showNotification') && str_contains($sw, "addEventListener('notificationclick'"), 'service worker handles push and clicks');
$html = (string) file_get_contents(dirname(__DIR__) . '/public_html/index.html');
platform_assert(str_contains($html, 'Alert me when a routine runs') && str_contains($html, 'Send test alert') && str_contains($html, '/assets/simco-push.js'), 'Routines card has the alert toggle and test button');

platform_stop($site, $sitePipes);
platform_stop($fake, $fakePipes);
@unlink($log);
echo "platform-38-push-alerts: ok\n";
