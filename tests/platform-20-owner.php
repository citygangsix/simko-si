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
file_put_contents($cfgFile, "<?php\ndeclare(strict_types=1);\nreturn " . var_export($cfg, true) . ";\n");
[$missing, $missingPipes] = platform_site($missingPrivate, 8834);
$m = platform_signup(8834, 'missing-' . getmypid() . '@simkosi.test');
$deniedMissing = platform_api(8834, '/api/simco/turn', ['text' => 'Say hi'], $m['token']);
platform_assert($deniedMissing['status'] === 403, 'with owner_access missing from config everyone is refused');
platform_assert($calls() === $before, 'no xAI call was made in either default-deny case');
platform_stop($missing, $missingPipes);

platform_stop($mock, $mockPipes);
@unlink($log);
fwrite(STDOUT, "owner-only tests passed\n");
