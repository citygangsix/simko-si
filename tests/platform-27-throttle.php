<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Wrong-password guesses are throttled per account and per network; a fresh
// install gets the voice_id columns.
$private = platform_private('throttle', ['paywall' => false]);
$cfgFile = $private . '/config.php';
$cfg = require $cfgFile;
$cfg['throttle'] = ['account_failures' => 3, 'ip_failures' => 6, 'window_seconds' => 900];
file_put_contents($cfgFile, "<?php\ndeclare(strict_types=1);\nreturn " . var_export($cfg, true) . ";\n");
[$site, $pipes] = platform_site($private, 8878);
$a = 'thr-a-' . getmypid() . '@simkosi.test';
$b = 'thr-b-' . getmypid() . '@simkosi.test';
foreach ([$a, $b] as $e) {
    $s = platform_api(8878, '/api/auth', ['op' => 'signup', 'email' => $e, 'password' => 'reef-turtle-8']);
    platform_assert($s['status'] === 200, 'signup ' . $e);
}
$ok = platform_api(8878, '/api/auth', ['op' => 'signin', 'email' => $a, 'password' => 'reef-turtle-8']);
platform_assert($ok['status'] === 200, 'right password signs in');
for ($i = 0; $i < 3; $i++) {
    $w = platform_api(8878, '/api/auth', ['op' => 'signin', 'email' => $a, 'password' => 'wrong-' . $i]);
    platform_assert($w['status'] === 401, 'wrong guess ' . ($i + 1) . ' refused');
}
$locked = platform_api(8878, '/api/auth', ['op' => 'signin', 'email' => $a, 'password' => 'reef-turtle-8']);
platform_assert($locked['status'] === 429, 'account locked after 3 wrong guesses, even with the right password');
platform_assert(str_contains((string) ($locked['data']['error'] ?? ''), 'Try again in'), 'lockout message says when');
$other = platform_api(8878, '/api/auth', ['op' => 'signin', 'email' => $b, 'password' => 'reef-turtle-8']);
platform_assert($other['status'] === 200, 'another account still signs in');
for ($i = 0; $i < 3; $i++) {
    platform_api(8878, '/api/auth', ['op' => 'signin', 'email' => 'ghost' . $i . '@simkosi.test', 'password' => 'x-wrong-1']);
}
$ipLocked = platform_api(8878, '/api/auth', ['op' => 'signin', 'email' => $b, 'password' => 'reef-turtle-8']);
platform_assert($ipLocked['status'] === 429, 'network locked after 6 wrong guesses across accounts');
for ($i = 0; $i < 7; $i++) {
    $g = platform_api(8878, '/api/auth', ['op' => 'reset-password', 'reset_token' => bin2hex(random_bytes(16)), 'password' => 'new-pass-99']);
}
platform_assert($g['status'] === 429, 'reset-code guessing is throttled too');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$cols = array_column($db->query('PRAGMA table_info(chats)')->fetchAll(PDO::FETCH_ASSOC), 'name');
platform_assert(in_array('voice_id', $cols, true), 'fresh install has chats.voice_id');
$cols = array_column($db->query('PRAGMA table_info(agents)')->fetchAll(PDO::FETCH_ASSOC), 'name');
platform_assert(in_array('voice_id', $cols, true), 'fresh install has agents.voice_id');
platform_stop($site, $pipes);
fwrite(STDOUT, "throttle tests passed\n");
