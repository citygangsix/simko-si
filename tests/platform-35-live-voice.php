<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

function live_voice_age_session(string $private, string $sessionId, int $secondsAgo = 180): void
{
    $db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
    $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $db->prepare('UPDATE live_voice_sessions SET started_at = started_at - ? WHERE id = ?');
    $stmt->execute([$secondsAgo, $sessionId]);
}


$mockPort = 19000 + (getmypid() % 800);
$sitePort = $mockPort + 1;
[$mock, $mockPipes] = platform_mock($mockPort);
$private = platform_private('live-voice', ['paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'live_voice' => [
        'user_daily_minutes' => 10,
        'site_daily_minutes' => 60,
        'model' => 'grok-voice-latest',
        'token_ttl_seconds' => 300,
    ],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$a = platform_signup($sitePort, 'live-a-' . getmypid() . '@simkosi.test');
$b = platform_signup($sitePort, 'live-b-' . getmypid() . '@simkosi.test');

$anon = platform_api($sitePort, '/api/voice/realtime', ['voice' => 'coral']);
platform_assert($anon['status'] === 401, 'signed out cannot mint a live-voice token');

$mint = platform_api($sitePort, '/api/voice/realtime', ['voice' => 'coral'], $a['token']);
platform_assert($mint['status'] === 200 && !empty($mint['data']['ok']) && !empty($mint['data']['value']), 'signed-in person can mint a live-voice token');
platform_assert(!empty($mint['data']['session_id']) && !empty($mint['data']['mock']), 'mint returns a session id and marks the local mock');
platform_assert(($mint['data']['remaining_user_seconds'] ?? 0) === 10 * 60, 'a new person has the 10-minute cap left');
platform_assert(($mint['data']['remaining_site_seconds'] ?? 0) === 60 * 60, 'the site starts with 60 minutes left');
platform_assert(($mint['data']['xai_voice'] ?? '') === 'carina', 'coral maps to the xAI voice');
$raw = json_encode($mint['data']);
platform_assert(!str_contains($raw, 'xai-local-mock'), 'the site key is never sent to the browser');
platform_assert(!str_contains($raw, 'xai_api_key'), 'the key field is not in the mint reply');
platform_assert($mint['data']['value'] === 'xai-realtime-client-secret-mock', 'the browser receives only the ephemeral token');
live_voice_age_session($private, (string) $mint['data']['session_id']);

$quota = platform_api($sitePort, '/api/voice/quota', [], $a['token']);
platform_assert($quota['status'] === 200 && ($quota['data']['remaining_user_seconds'] ?? 0) === 600, 'quota shows remaining minutes before a session');

$use = platform_api($sitePort, '/api/voice/usage', [
    'session_id' => $mint['data']['session_id'],
    'seconds' => 45,
], $a['token']);
platform_assert($use['status'] === 200 && (int) ($use['data']['added_seconds'] ?? 0) === 45, 'usage records 45 seconds');
platform_assert((int) ($use['data']['remaining_user_seconds'] ?? -1) === 555, 'the cap counter moves after usage');
platform_assert((int) ($use['data']['user_used_seconds'] ?? 0) === 45, 'used seconds are stored per person');

$again = platform_api($sitePort, '/api/voice/usage', [
    'session_id' => $mint['data']['session_id'],
    'seconds' => 15,
], $a['token']);
platform_assert((int) ($again['data']['remaining_user_seconds'] ?? -1) === 540, 'a later report subtracts more time');

$other = platform_api($sitePort, '/api/voice/usage', [
    'session_id' => $mint['data']['session_id'],
    'seconds' => 10,
], $b['token']);
platform_assert($other['status'] === 404, 'another person cannot report against this session');

$steal = platform_api($sitePort, '/api/voice/usage', [
    'session_id' => 'ffffffffffffffffffffffffffffffff',
    'seconds' => 10,
], $b['token']);
platform_assert($steal['status'] === 404, 'an unknown session is refused');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);

// Tight caps: 1 minute per person, 2 minutes site-wide.
$mockPort = $sitePort + 2;
$sitePort = $mockPort + 1;
[$mock, $mockPipes] = platform_mock($mockPort);
$private = platform_private('live-voice-caps', ['paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'live_voice' => [
        'user_daily_minutes' => 1,
        'site_daily_minutes' => 2,
        'token_ttl_seconds' => 300,
    ],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$a = platform_signup($sitePort, 'cap-a-' . getmypid() . '@simkosi.test');
$b = platform_signup($sitePort, 'cap-b-' . getmypid() . '@simkosi.test');
$c = platform_signup($sitePort, 'cap-c-' . getmypid() . '@simkosi.test');

$mintA = platform_api($sitePort, '/api/voice/realtime', ['voice' => 'coral'], $a['token']);
platform_assert($mintA['status'] === 200, 'person A can start under a 1-minute cap');
live_voice_age_session($private, (string) $mintA['data']['session_id']);
$fillA = platform_api($sitePort, '/api/voice/usage', [
    'session_id' => $mintA['data']['session_id'],
    'seconds' => 60,
], $a['token']);
platform_assert((int) ($fillA['data']['remaining_user_seconds'] ?? -1) === 0, 'person A can use the full minute');
$blockedA = platform_api($sitePort, '/api/voice/realtime', ['voice' => 'coral'], $a['token']);
platform_assert($blockedA['status'] === 429 && ($blockedA['data']['live_voice_cap'] ?? '') === 'user', 'person A is blocked at the personal cap');
platform_assert(str_contains((string) ($blockedA['data']['error'] ?? ''), '1 minute'), 'the personal cap message names the limit');

$mintB = platform_api($sitePort, '/api/voice/realtime', ['voice' => 'coral'], $b['token']);
platform_assert($mintB['status'] === 200, 'person B still has their own minute');
live_voice_age_session($private, (string) $mintB['data']['session_id']);
$fillB = platform_api($sitePort, '/api/voice/usage', [
    'session_id' => $mintB['data']['session_id'],
    'seconds' => 60,
], $b['token']);
platform_assert((int) ($fillB['data']['remaining_site_seconds'] ?? -1) === 0, 'the site cap is reached after two minutes');
$blockedC = platform_api($sitePort, '/api/voice/realtime', ['voice' => 'coral'], $c['token']);
platform_assert($blockedC['status'] === 429 && ($blockedC['data']['live_voice_cap'] ?? '') === 'site', 'a third person is blocked by the site cap');
platform_assert(str_contains((string) ($blockedC['data']['error'] ?? ''), '2 minutes'), 'the site cap message names the limit');

$log = $private . '/data/live-voice.log';
platform_assert(is_file($log) && trim((string) file_get_contents($log)) !== '', 'site-wide use is written to the live-voice log');
$logText = (string) file_get_contents($log);
platform_assert(!str_contains($logText, 'xai-local-mock') && !str_contains($logText, $a['token']), 'the log does not contain keys or session tokens');

$page = (string) file_get_contents(dirname(__DIR__) . '/public_html/index.html');
foreach (['id="liveVoiceRemain"', 'id="liveVoiceTranscript"', 'id="liveVoice"'] as $needle) {
    platform_assert(str_contains($page, $needle), 'the chat has ' . $needle);
}

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "live voice tests passed\n");
