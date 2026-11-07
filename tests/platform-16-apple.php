<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$keyDir = sys_get_temp_dir() . '/simko-apple-site-' . getmypid();
$p8 = $keyDir . '/AuthKey.p8';
$rsa = $keyDir . '/apple-rsa.pem';
$capture = $keyDir . '/apple-capture.txt';
$modeFile = $keyDir . '/apple-mode.txt';
@mkdir($keyDir . '/data', 0700, true);
file_put_contents($modeFile, 'ok');
exec('openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out ' . escapeshellarg($p8));
exec('openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out ' . escapeshellarg($rsa));
platform_assert(is_file($p8) && is_file($rsa), 'test keys were created outside the repo');

$applePort = 9073;
$sitePort = 9072;
$cmd = 'php -S 127.0.0.1:' . $applePort . ' ' . escapeshellarg(dirname(__DIR__) . '/tests/fake-apple.php');
$env = getenv();
if (!is_array($env)) {
    $env = [];
}
$env['SIMKO_APPLE_KEY'] = $rsa;
$env['SIMKO_APPLE_KID'] = 'TESTKEY1';
$env['SIMKO_APPLE_CAPTURE'] = $capture;
$env['SIMKO_APPLE_MODE_FILE'] = $modeFile;
$env['SIMKO_APPLE_DB'] = $keyDir . '/data/simko.sqlite';
$env['SIMKO_APPLE_AUD'] = 'com.simkosi.web';
$apple = proc_open($cmd, [['pipe', 'r'], ['pipe', 'w'], ['pipe', 'w']], $applePipes, dirname(__DIR__), $env);

$ready = platform_private('apple-site', ['oauth' => true], [
    'oauth' => [
        'google' => ['client_id' => ''],
        'apple' => [
            'client_id' => 'com.simkosi.web',
            'team_id' => 'TEAM123456',
            'key_id' => 'TESTKEY1',
            'p8_path' => $p8,
            'authorize_url' => 'https://appleid.apple.com/auth/authorize',
            'token_url' => 'http://127.0.0.1:' . $applePort . '/auth/token',
            'jwks_url' => 'http://127.0.0.1:' . $applePort . '/auth/keys',
            'redirect_url' => 'http://127.0.0.1:' . $sitePort . '/api/oauth/callback',
            'scope' => 'name email',
        ],
    ],
]);
[$site, $sitePipes] = platform_site($ready, $sitePort);
$off = platform_private('apple-off', ['oauth' => true]);
[$offSite, $offPipes] = platform_site($off, 9074);
$hidden = platform_api(9074, '/api/platform', ['op' => 'oauth-start', 'provider' => 'apple']);
platform_assert($hidden['status'] === 404, 'Apple stays hidden until Services ID, Team ID, Key ID, and the p8 are set');
platform_stop($offSite, $offPipes);

$start = platform_api($sitePort, '/api/platform', ['op' => 'oauth-start', 'provider' => 'apple']);
platform_assert($start['status'] === 200 && str_contains((string) $start['data']['url'], 'response_mode=form_post'), 'Apple start asks for form_post');
platform_assert(str_contains((string) $start['data']['url'], 'nonce='), 'Apple start sends a nonce');
$state = (string) $start['data']['state'];
$userJson = json_encode(['email' => 'ada@privaterelay.appleid.com']);
$ctx = stream_context_create(['http' => [
    'method' => 'POST',
    'header' => "Content-Type: application/x-www-form-urlencoded\r\n",
    'content' => http_build_query([
        'code' => 'apple-code',
        'state' => $state,
        'user' => $userJson,
    ]),
    'ignore_errors' => true,
    'timeout' => 20,
]]);
$html = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/oauth/callback', false, $ctx);
platform_assert(is_string($html) && str_contains($html, 'ada@privaterelay.appleid.com'), 'form_post callback creates the Apple account');
$posted = file_get_contents($capture);
parse_str((string) $posted, $form);
$jwt = (string) ($form['client_secret'] ?? '');
$pieces = explode('.', $jwt);
$pad = static function (string $part): string {
    $part = strtr($part, '-_', '+/');
    return $part . str_repeat('=', (4 - strlen($part) % 4) % 4);
};
$appleHeader = json_decode(base64_decode($pad($pieces[0])), true);
$appleClaims = json_decode(base64_decode($pad($pieces[1])), true);
platform_assert(($appleHeader['alg'] ?? '') === 'ES256' && ($appleHeader['kid'] ?? '') === 'TESTKEY1', 'client_secret is an ES256 JWT');
platform_assert(($appleClaims['iss'] ?? '') === 'TEAM123456' && ($appleClaims['sub'] ?? '') === 'com.simkosi.web', 'client_secret names the team and Services ID');
platform_assert(($appleClaims['aud'] ?? '') === 'https://appleid.apple.com', 'client_secret audience is Apple');
$rawSig = base64_decode($pad($pieces[2]));
$r = substr($rawSig, 0, 32);
$s = substr($rawSig, 32, 32);
$derInt = static function (string $bin): string {
    $bin = ltrim($bin, "\x00");
    if ($bin === '' || (ord($bin[0]) & 0x80)) {
        $bin = "\x00" . $bin;
    }
    return "\x02" . chr(strlen($bin)) . $bin;
};
$derBody = $derInt($r) . $derInt($s);
$der = "\x30" . chr(strlen($derBody)) . $derBody;
$pub = openssl_pkey_get_details(openssl_pkey_get_private((string) file_get_contents($p8)));
platform_assert(openssl_verify($pieces[0] . '.' . $pieces[1], $der, $pub['key'], OPENSSL_ALGO_SHA256) === 1, 'client_secret signature matches the p8');

$relay = new PDO('sqlite:' . $ready . '/data/simko.sqlite');
$flag = (int) $relay->query("SELECT email_relay FROM oauth_identities WHERE provider = 'apple'")->fetchColumn();
platform_assert($flag === 1, 'a private relay email is marked');

$again = platform_api($sitePort, '/api/platform', ['op' => 'oauth-start', 'provider' => 'apple']);
$ctx2 = stream_context_create(['http' => [
    'method' => 'POST',
    'header' => "Content-Type: application/x-www-form-urlencoded\r\n",
    'content' => http_build_query(['code' => 'apple-code-2', 'state' => $again['data']['state']]),
    'ignore_errors' => true,
]]);
$html2 = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/oauth/callback', false, $ctx2);
platform_assert(is_string($html2) && str_contains($html2, 'ada@privaterelay.appleid.com'), 'a later Apple sign-in links the same subject');

file_put_contents($modeFile, 'badnonce');
$badStart = platform_api($sitePort, '/api/platform', ['op' => 'oauth-start', 'provider' => 'apple']);
$badCtx = stream_context_create(['http' => [
    'method' => 'POST',
    'header' => "Content-Type: application/x-www-form-urlencoded\r\n",
    'content' => http_build_query(['code' => 'bad', 'state' => $badStart['data']['state']]),
    'ignore_errors' => true,
]]);
$bad = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/oauth/callback', false, $badCtx);
platform_assert(is_string($bad) && str_contains($bad, 'not accept'), 'a bad nonce is rejected');

platform_stop($site, $sitePipes);
platform_stop($apple, $applePipes);
fwrite(STDOUT, "apple tests passed\n");
