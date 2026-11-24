<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Two-step sign-in (TOTP + 8 backup codes, code-step throttle) and the signed-in devices list.
function t35_b32decode(string $s): string
{
    $a = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    $bits = '';
    foreach (str_split(strtoupper(str_replace(' ', '', $s))) as $c) {
        $bits .= str_pad(decbin(strpos($a, $c)), 5, '0', STR_PAD_LEFT);
    }
    $out = '';
    foreach (str_split($bits, 8) as $b) {
        if (strlen($b) === 8) {
            $out .= chr(bindec($b));
        }
    }
    return $out;
}
function t35_totp(string $secret, int $offset = 0): string
{
    $step = intdiv(time(), 30) + $offset;
    $h = hash_hmac('sha1', pack('N2', 0, $step), t35_b32decode($secret), true);
    $o = ord($h[19]) & 15;
    $n = ((ord($h[$o]) & 127) << 24) | (ord($h[$o + 1]) << 16) | (ord($h[$o + 2]) << 8) | ord($h[$o + 3]);
    return str_pad((string) ($n % 1000000), 6, '0', STR_PAD_LEFT);
}
function t35_wait_new_step(): void
{
    $left = 30 - (time() % 30);
    sleep($left + 1);
}

$private = platform_private('twofa', ['memory' => true, 'paywall' => false], [
    'throttle' => ['account_failures' => 5, 'ip_failures' => 40, 'window_seconds' => 900],
]);
[$site, $sitePipes] = platform_site($private, 8885);
$email = 'tfa-' . getmypid() . '@simkosi.test';
$a = platform_signup(8885, $email);
$tokA = $a['token'];

// Off by default: password alone signs in.
$st = platform_api(8885, '/api/auth', ['op' => 'twofa-status'], $tokA);
platform_assert($st['status'] === 200 && $st['data']['enabled'] === false, 'two-step is off by default');
$plain = platform_api(8885, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'reef-turtle-8']);
platform_assert(!empty($plain['data']['token']) && empty($plain['data']['twofa_required']), 'without two-step the password signs in');
platform_assert(platform_api(8885, '/api/auth', ['op' => 'twofa-setup'])['status'] === 401, 'setup needs a signed-in user');

// Setup + enable.
$setup = platform_api(8885, '/api/auth', ['op' => 'twofa-setup'], $tokA);
$secret = (string) ($setup['data']['secret'] ?? '');
platform_assert(strlen($secret) === 32 && str_starts_with((string) $setup['data']['otpauth'], 'otpauth://totp/Simko%20SI'), 'setup returns a 160-bit secret and an otpauth link');
$bad = platform_api(8885, '/api/auth', ['op' => 'twofa-enable', 'code' => '000000'], $tokA);
platform_assert($bad['status'] === 400, 'a wrong code does not turn it on');
$on = platform_api(8885, '/api/auth', ['op' => 'twofa-enable', 'code' => t35_totp($secret)], $tokA);
$codes = $on['data']['backup_codes'] ?? [];
platform_assert($on['status'] === 200 && $on['data']['enabled'] === true && count($codes) === 8 && count(array_unique($codes)) === 8, 'the right code turns it on and gives 8 different backup codes');
platform_assert($on['data']['backup_codes_left'] === 8, 'status counts 8 backup codes');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$raw = (string) $db->query('SELECT secret_cipher FROM user_totp')->fetchColumn();
platform_assert($raw !== '' && !str_contains($raw, $secret), 'the secret is stored sealed, not in plain text');
$hashes = implode(',', $db->query('SELECT code_hash FROM user_backup_codes')->fetchAll(PDO::FETCH_COLUMN));
platform_assert(!str_contains($hashes, $codes[0]), 'backup codes are stored hashed');

// Sign-in now needs the code.
$pw = platform_api(8885, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'reef-turtle-8']);
platform_assert($pw['status'] === 200 && $pw['data']['twofa_required'] === true && empty($pw['data']['token']) && strlen((string) $pw['data']['challenge']) === 48, 'with two-step on, the password alone gives no session');
$wrongPw = platform_api(8885, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'nope-nope-1']);
platform_assert($wrongPw['status'] === 401 && empty($wrongPw['data']['challenge']), 'a wrong password never reaches the code step');
$ch = (string) $pw['data']['challenge'];
$replayCode = t35_totp($secret);
$miss = platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => $ch, 'code' => '123456']);
platform_assert($miss['status'] === 401 && empty($miss['data']['token']), 'a wrong code is refused');
$fake = platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => str_repeat('a', 48), 'code' => t35_totp($secret)]);
platform_assert($fake['status'] === 401 && !empty($fake['data']['twofa_restart']), 'a made-up challenge is refused');
// The code used to enable was this step; replaying the same step is refused, so wait for the next one.
$replay = platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => $ch, 'code' => $replayCode]);
platform_assert($replay['status'] === 401, 'an app code that was already used cannot be used again');
t35_wait_new_step();
$ok = platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => $ch, 'code' => t35_totp($secret)]);
platform_assert($ok['status'] === 200 && !empty($ok['data']['token']) && $ok['data']['email'] === $email, 'the right code finishes sign-in');
$again = platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => $ch, 'code' => t35_totp($secret)]);
platform_assert($again['status'] === 401, 'a challenge works only once');

// Backup code: works once.
$ch2 = (string) platform_api(8885, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'reef-turtle-8'])['data']['challenge'];
$bk = platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => $ch2, 'code' => strtoupper($codes[0])]);
platform_assert($bk['status'] === 200 && !empty($bk['data']['token']), 'a backup code signs in (any case)');
$ch3 = (string) platform_api(8885, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'reef-turtle-8'])['data']['challenge'];
$bk2 = platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => $ch3, 'code' => $codes[0]]);
platform_assert($bk2['status'] === 401, 'the same backup code does not work twice');
$left = platform_api(8885, '/api/auth', ['op' => 'twofa-status'], $tokA);
platform_assert($left['data']['backup_codes_left'] === 7, '7 backup codes left after one is used');

// Throttle on the code step: 5 misses per account, then 429 even with a right code.
for ($i = 0; $i < 4; $i++) {
    platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => $ch3, 'code' => '00000' . $i]);
}
$ch4 = (string) platform_api(8885, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'reef-turtle-8'])['data']['challenge'];
$locked = platform_api(8885, '/api/auth', ['op' => 'twofa-verify', 'challenge' => $ch4, 'code' => $codes[1]]);
platform_assert($locked['status'] === 429, 'after 5 wrong codes the code step is locked for a while');
$db->exec("DELETE FROM auth_throttle");

// Turn off needs password AND code.
$offNoCode = platform_api(8885, '/api/auth', ['op' => 'twofa-disable', 'password' => 'reef-turtle-8', 'code' => ''], $tokA);
platform_assert($offNoCode['status'] === 401, 'turning off without a code is refused');
$offBadPw = platform_api(8885, '/api/auth', ['op' => 'twofa-disable', 'password' => 'wrong-pass-9', 'code' => $codes[2]], $tokA);
platform_assert($offBadPw['status'] === 401, 'turning off with a wrong password is refused');
$stillOn = platform_api(8885, '/api/auth', ['op' => 'twofa-status'], $tokA);
platform_assert($stillOn['data']['enabled'] === true && $stillOn['data']['backup_codes_left'] === 7, 'a refused turn-off does not burn a backup code');
$off = platform_api(8885, '/api/auth', ['op' => 'twofa-disable', 'password' => 'reef-turtle-8', 'code' => $codes[3]], $tokA);
platform_assert($off['status'] === 200 && $off['data']['enabled'] === false, 'password plus a code turns it off');
$plain2 = platform_api(8885, '/api/auth', ['op' => 'signin', 'email' => $email, 'password' => 'reef-turtle-8']);
platform_assert(!empty($plain2['data']['token']), 'after turning off, the password alone signs in again');

// Devices.
$b = platform_signup(8885, 'tfa-b-' . getmypid() . '@simkosi.test');
$devs = platform_api(8885, '/api/auth', ['op' => 'devices'], $tokA);
$rows = $devs['data']['devices'] ?? [];
platform_assert($devs['status'] === 200 && count($rows) >= 4, 'the list shows each session (' . count($rows) . ')');
platform_assert($rows[0]['current'] === true && count(array_filter($rows, static fn ($r) => $r['current'])) === 1, 'exactly one row is this device, listed first');
platform_assert(isset($rows[0]['browser'], $rows[0]['os'], $rows[0]['ip'], $rows[0]['created_at'], $rows[0]['last_seen']) && $rows[0]['ip'] === '127.0.x.x', 'rows have browser, OS, masked IP and times');
$other = null;
foreach ($rows as $r) {
    if (!$r['current']) {
        $other = $r;
        break;
    }
}
$selfOut = platform_api(8885, '/api/auth', ['op' => 'device-signout', 'device_id' => $rows[0]['id']], $tokA);
platform_assert($selfOut['status'] === 400, 'the current device cannot be removed from the list (use Sign out)');
$bRows = platform_api(8885, '/api/auth', ['op' => 'devices'], $b['token'])['data']['devices'] ?? [];
$steal = platform_api(8885, '/api/auth', ['op' => 'device-signout', 'device_id' => $bRows[0]['id']], $tokA);
platform_assert($steal['status'] === 404, 'another person\'s device cannot be signed out');
platform_assert(platform_api(8885, '/api/auth', ['op' => 'me'], $b['token'])['data']['ok'] === true, 'that person stays signed in');
$one = platform_api(8885, '/api/auth', ['op' => 'device-signout', 'device_id' => $other['id']], $tokA);
platform_assert($one['status'] === 200 && count($one['data']['devices']) === count($rows) - 1, 'one other device is signed out');
platform_assert(platform_api(8885, '/api/auth', ['op' => 'me'], $ok['data']['token'])['data']['ok'] === false
    || platform_api(8885, '/api/auth', ['op' => 'me'], $bk['data']['token'])['data']['ok'] === false
    || platform_api(8885, '/api/auth', ['op' => 'me'], $plain['data']['token'])['data']['ok'] === false
    || platform_api(8885, '/api/auth', ['op' => 'me'], $plain2['data']['token'])['data']['ok'] === false, 'the signed-out session no longer works');
$all = platform_api(8885, '/api/auth', ['op' => 'devices-signout-others'], $tokA);
platform_assert($all['status'] === 200 && count($all['data']['devices']) === 1 && $all['data']['devices'][0]['current'] === true, 'sign out all others leaves only this device');
foreach ([$ok, $bk, $plain, $plain2] as $gone) {
    platform_assert(platform_api(8885, '/api/auth', ['op' => 'me'], $gone['data']['token'])['data']['ok'] === false, 'other session is signed out');
}
platform_assert(platform_api(8885, '/api/auth', ['op' => 'me'], $tokA)['data']['ok'] === true, 'this device stays signed in');
platform_assert(platform_api(8885, '/api/auth', ['op' => 'me'], $b['token'])['data']['ok'] === true, 'other people are never signed out');
platform_assert(platform_api(8885, '/api/auth', ['op' => 'devices'])['status'] === 401, 'signed out cannot list devices');

$page = (string) file_get_contents(dirname(__DIR__) . '/public_html/index.html');
foreach (['id="authTwofaForm"', 'id="modalTwofaCode"', 'id="twofaCard"', 'id="twofaQr"', 'id="devicesCard"', 'id="devicesSignOutOthers"', 'id="accountTwofa"', 'id="accountDevices"', 'simco-security.js'] as $needle) {
    platform_assert(str_contains($page, $needle), 'the page has ' . $needle);
}
platform_assert(!preg_match('#https?://[^"\']*(qr|chart\.googleapis)#i', $page . file_get_contents(dirname(__DIR__) . '/public_html/assets/simco-security.js')), 'no outside QR service');
platform_stop($site, $sitePipes);
