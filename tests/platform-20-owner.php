<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Owner-only access to the shared xAI key. The mock records every xAI request it receives.
$log = sys_get_temp_dir() . '/simko-owner-calls-' . getmypid() . '.log';
@unlink($log);
putenv('MOCK_XAI_LOG=' . $log);
$mockPort = 8831;
$sitePort = 8832;
[$mock, $mockPipes] = platform_mock($mockPort);
@unlink($log); // drop the readiness probe
$calls = static function () use ($log): int {
    return is_file($log) ? count(array_filter(explode("\n", (string) file_get_contents($log)))) : 0;
};

$ownerEmail = 'owner-' . getmypid() . '@simkosi.test';
$private = platform_private('owner', ['search' => true, 'images' => true, 'agents' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [strtoupper($ownerEmail)], 'user_ids' => []],
    'grok_access' => 'owner',
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$owner = platform_signup($sitePort, $ownerEmail);
$guest = platform_signup($sitePort, 'citygangsix+simkoparity-' . getmypid() . '@gmail.com');

$ok = platform_api($sitePort, '/api/simco/turn', ['text' => 'Say hi'], $owner['token']);
platform_assert($ok['status'] === 200 && str_contains((string) ($ok['data']['everyday'] ?? ''), 'reef'), 'the owner (matched by email, any case) gets a Grok reply');
platform_assert($calls() === 1, 'the owner turn made exactly one xAI call');

$before = $calls();
$no = platform_api($sitePort, '/api/simco/turn', ['text' => 'Say hi'], $guest['token']);
platform_assert($no['status'] === 403 && ($no['data']['error'] ?? '') === 'Grok is not enabled for this account.', 'a non-owner chat is refused with a clear message');
$img = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'a blue circle'], $guest['token']);
platform_assert(in_array($img['status'], [402, 403], true), 'a non-owner (non-subscriber) picture is refused');
$stt = platform_api($sitePort, '/api/voice/transcribe', ['audio' => base64_encode('RIFF....'), 'mime' => 'audio/wav'], $guest['token']);
platform_assert($stt['status'] === 403, 'a non-owner transcription is refused');
$agent = platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'A', 'persona' => 'Brief.'], $guest['token']);
$stream = platform_api($sitePort, '/api/agent-stream', ['agent_id' => (int) ($agent['data']['agent']['id'] ?? 0), 'text' => 'hi'], $guest['token']);
platform_assert(in_array($stream['status'], [403, 404], true), 'a non-owner agent stream is refused');
$tts = @file_get_contents('http://127.0.0.1:' . $sitePort . '/api/voice/speak?voice=coral&text=hi', false, stream_context_create(['http' => [
    'header' => "Origin: http://127.0.0.1:{$sitePort}\r\nAuthorization: Bearer {$guest['token']}\r\n", 'ignore_errors' => true,
]]));
platform_assert(str_contains((string) ($http_response_header[0] ?? ''), '403'), 'a non-owner text to speech is refused');
platform_assert($calls() === $before, 'no xAI call was made for the non-owner');

$anon = platform_api($sitePort, '/api/simco/turn', ['text' => 'Say hi']);
platform_assert($anon['status'] === 401, 'a signed-out chat is refused');
platform_assert($calls() === $before, 'no xAI call was made when signed out');
platform_stop($site, $sitePipes);

// Default deny: no owner configured means nobody, not everybody.
$emptyPrivate = platform_private('owner-empty', ['search' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [], 'user_ids' => []],
    'grok_access' => 'owner',
]);
[$empty, $emptyPipes] = platform_site($emptyPrivate, 8833);
$first = platform_signup(8833, 'first-' . getmypid() . '@simkosi.test');
$denied = platform_api(8833, '/api/simco/turn', ['text' => 'Say hi'], $first['token']);
platform_assert($denied['status'] === 403, 'with no owner configured even the first account is refused');
platform_stop($empty, $emptyPipes);

$missingPrivate = platform_private('owner-missing', ['paywall' => false], ['xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1']);
$cfgFile = $missingPrivate . '/config.php';
$cfg = require $cfgFile;
unset($cfg['owner_access']);
$cfg['grok_access'] = 'owner';
file_put_contents($cfgFile, "<?php\ndeclare(strict_types=1);\nreturn " . var_export($cfg, true) . ";\n");
[$missing, $missingPipes] = platform_site($missingPrivate, 8834);
$m = platform_signup(8834, 'missing-' . getmypid() . '@simkosi.test');
$deniedMissing = platform_api(8834, '/api/simco/turn', ['text' => 'Say hi'], $m['token']);
platform_assert($deniedMissing['status'] === 403, 'with owner_access missing from config everyone is refused');
platform_assert($calls() === $before, 'no xAI call was made in either default-deny case');
platform_stop($missing, $missingPipes);

// Open access (the default since 2026-11-23): every confirmed account may use Grok under the spend caps.
$openPrivate = platform_private('owner-open', ['search' => true, 'images' => true, 'browse' => true, 'code' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
]);
[$open, $openPipes] = platform_site($openPrivate, 8835);
$demo = platform_signup(8835, 'demo-' . getmypid() . '@simkosi.test');
$odb = new PDO('sqlite:' . $openPrivate . '/data/simko.sqlite');
$odb->prepare('UPDATE users SET confirmed = 0 WHERE email = ?')->execute(['demo-' . getmypid() . '@simkosi.test']);
$before = $calls();
$unconfirmed = platform_api(8835, '/api/simco/turn', ['text' => 'Say hi'], $demo['token']);
platform_assert($unconfirmed['status'] === 403 && !empty($unconfirmed['data']['confirm_needed']), 'an unconfirmed account is asked to confirm its email first');
platform_assert($calls() === $before, 'no xAI call for an unconfirmed account');
$odb->prepare('UPDATE users SET confirmed = 1 WHERE email = ?')->execute(['demo-' . getmypid() . '@simkosi.test']);
$chat = platform_api(8835, '/api/simco/turn', ['text' => 'Say hi'], $demo['token']);
platform_assert($chat['status'] === 200 && str_contains((string) ($chat['data']['everyday'] ?? ''), 'reef'), 'a confirmed non-owner gets a Grok reply');
$models = platform_api(8835, '/api/platform', ['op' => 'models'], $demo['token']);
platform_assert(($models['data']['spend']['demo'] ?? null) === true && (float) ($models['data']['spend']['cap_usd'] ?? 0) === 1.0, 'a demo account sees its $1 daily limit');
$quote = platform_api(8835, '/api/platform', ['op' => 'image-quote'], $demo['token']);
platform_assert(($quote['data']['access']['role'] ?? '') === 'demo' && !empty($quote['data']['access']['allowed']) && str_contains((string) $quote['data']['access']['quote'], 'free during preview'), 'a demo account may make pictures, not billed');
$sites = platform_api(8835, '/api/platform', ['op' => 'browse-sites'], $demo['token']);
platform_assert($sites['status'] === 403, 'the allowed-sites editor stays owner-only');
$jobs = platform_api(8835, '/api/platform', ['op' => 'code-jobs'], $demo['token']);
platform_assert($jobs['status'] === 403, 'Code tab jobs stay owner-only');
platform_stop($open, $openPipes);

platform_stop($mock, $mockPipes);
@unlink($log);
fwrite(STDOUT, "owner-only tests passed\n");
