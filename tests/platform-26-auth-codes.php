<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Confirm and reset codes go by email only: never in an API reply unless a local test server opts in.
$private = platform_private('authcodes', ['paywall' => false]);
$cfgFile = $private . '/config.php';
$cfg = require $cfgFile;
unset($cfg['dev_codes_in_reply']);
file_put_contents($cfgFile, "<?php\ndeclare(strict_types=1);\nreturn " . var_export($cfg, true) . ";\n");
[$site, $pipes] = platform_site($private, 8879);
$email = 'codes-' . getmypid() . '@simkosi.test';
$signup = platform_api(8879, '/api/auth', ['op' => 'signup', 'email' => $email, 'password' => 'reef-turtle-8']);
platform_assert($signup['status'] === 200 && !empty($signup['data']['token']), 'signup still works');
platform_assert(!array_key_exists('dev_token', $signup['data']), 'signup reply has no confirm code');
$reset = platform_api(8879, '/api/auth', ['op' => 'request-reset', 'email' => $email]);
platform_assert($reset['status'] === 200 && !array_key_exists('dev_token', $reset['data']), 'reset reply has no reset code');
platform_assert(!preg_match('/[0-9a-f]{32}/', json_encode($reset['data'])), 'no 32-hex code anywhere in the reset reply');
$unknown = platform_api(8879, '/api/auth', ['op' => 'request-reset', 'email' => 'nobody-' . getmypid() . '@simkosi.test']);
platform_assert($unknown['status'] === 200 && $unknown['data'] == $reset['data'], 'known and unknown emails get the same reply');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$row = $db->query("SELECT reset_token FROM users WHERE email = " . $db->quote($email))->fetch();
platform_assert(is_array($row) && strlen((string) $row['reset_token']) === 32, 'the reset code is still created for the email');
$bad = platform_api(8879, '/api/auth', ['op' => 'reset-password', 'reset_token' => str_repeat('0', 32), 'password' => 'new-pass-99']);
platform_assert($bad['status'] === 400, 'a guessed code is refused');
$good = platform_api(8879, '/api/auth', ['op' => 'reset-password', 'reset_token' => (string) $row['reset_token'], 'password' => 'new-pass-99']);
platform_assert($good['status'] === 200, 'the emailed code still resets the password');
platform_stop($site, $pipes);
fwrite(STDOUT, "auth codes tests passed\n");
