<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$basePort = 21000 + (getmypid() % 20000);
$mockPort = $basePort + 1;
$sitePort = $basePort + 2;
$offPort = $basePort + 4;
[$mock, $mockPipes] = platform_mock($mockPort);
$private = platform_private('paywall', ['paywall' => true], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'square' => [
        'environment' => 'sandbox',
        'application_id' => 'sandbox-sq-app',
        'location_id' => 'sandbox-location',
        'access_token' => '',
        'api_base' => 'http://127.0.0.1:' . ($basePort + 3),
    ],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'pay-' . getmypid() . '@simkosi.test');
$token = $user['token'];

$health = file_get_contents('http://127.0.0.1:' . $sitePort . '/api/health');
platform_assert(is_string($health) && str_contains($health, '"paywall":true'), 'paywall flag is on for this test only');

for ($i = 1; $i <= 5; $i++) {
    $turn = platform_api($sitePort, '/api/simco/turn', [
        'text' => 'message ' . $i,
        'voice' => $i === 5,
    ], $token);
    platform_assert($turn['status'] === 200 && str_contains((string) ($turn['data']['everyday'] ?? ''), 'message ' . $i), 'free message ' . $i);
}
$voice = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $token);
platform_assert(($voice['data']['used'] ?? 0) === 5, 'five messages counted');
platform_assert(($voice['data']['plan_label'] ?? '') === '$9.99/month', 'plan label is $9.99/month');
platform_assert(($voice['data']['plan_amount'] ?? 0) === 999, 'plan amount is 999 cents');
platform_assert(($voice['data']['billing']['provider'] ?? '') === 'stripe', 'billing provider defaults to stripe');
platform_assert(($voice['data']['events'][0]['kind'] ?? '') === 'voice', 'the last turn is a voice turn');
$blocked = platform_api($sitePort, '/api/simco/turn', ['text' => 'one more'], $token);
platform_assert($blocked['status'] === 402 && !empty($blocked['data']['paywall']), 'sixth message opens the paywall');

$checkout = platform_api($sitePort, '/api/platform', ['op' => 'checkout'], $token);
platform_assert($checkout['status'] === 402 && str_contains((string) ($checkout['data']['error'] ?? ''), 'not connected'), 'unset Square token does not charge');

$trial = platform_api($sitePort, '/api/platform', ['op' => 'start-trial'], $token);
platform_assert($trial['status'] === 200 && ($trial['data']['status'] ?? '') === 'trial', 'free trial starts only after a tap');
$after = platform_api($sitePort, '/api/simco/turn', ['text' => 'during trial'], $token);
platform_assert($after['status'] === 200, 'trial allows another message without payment');

$offPrivate = platform_private('paywall-off', ['paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
]);
[$off, $offPipes] = platform_site($offPrivate, $offPort);
$offUser = platform_signup($offPort, 'off-' . getmypid() . '@simkosi.test');
$sixth = null;
for ($i = 1; $i <= 6; $i++) {
    $sixth = platform_api($offPort, '/api/simco/turn', ['text' => 'open ' . $i], $offUser['token']);
}
platform_assert($sixth['status'] === 200 && empty($sixth['data']['paywall']), 'paywall flag off does not cap messages');

platform_stop($off, $offPipes);
platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "paywall tests passed\n");
