<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$mockPort = 9091;
$sitePort = 9092;
[$mock, $mockPipes] = platform_mock($mockPort);
$private = platform_private('agent-stream', ['agents' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'stream_delay_ms' => 180,
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$user = platform_signup($sitePort, 'stream-' . getmypid() . '@simkosi.test');
$token = $user['token'];
$reef = platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'Reef', 'persona' => 'Warm'], $token);
$tide = platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'Tide', 'persona' => 'Careful'], $token);

$mh = curl_multi_init();
$handles = [];
foreach ([['id' => $reef['data']['agent']['id'], 'text' => 'alpha-marker'], ['id' => $tide['data']['agent']['id'], 'text' => 'beta-marker']] as $job) {
    $ch = curl_init('http://127.0.0.1:' . $sitePort . '/api/agent-stream');
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode(['token' => $token, 'agent_id' => $job['id'], 'text' => $job['text']]),
        CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Origin: http://127.0.0.1:' . $sitePort],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HEADER => true,
    ]);
    curl_multi_add_handle($mh, $ch);
    $handles[] = $ch;
}
$started = microtime(true);
do {
    $status = curl_multi_exec($mh, $running);
    curl_multi_select($mh, 0.05);
} while ($running > 0 && $status === CURLM_OK);
$elapsed = microtime(true) - $started;
$bodies = [];
foreach ($handles as $ch) {
    $raw = (string) curl_multi_getcontent($ch);
    platform_assert(str_contains($raw, 'X-Simko-Session: closed'), 'session lock is released before the stream');
    $bodies[] = $raw;
    curl_multi_remove_handle($mh, $ch);
}
curl_multi_close($mh);
platform_assert($elapsed < 0.9, 'the two streams overlapped, elapsed ' . round($elapsed, 3));
platform_assert(str_contains($bodies[0], 'alpha-marker') && !str_contains($bodies[0], 'beta-marker'), 'Reef did not receive Tide');
platform_assert(str_contains($bodies[1], 'beta-marker') && !str_contains($bodies[1], 'alpha-marker'), 'Tide did not receive Reef');
platform_assert(str_contains($bodies[0], 'Reef:') && str_contains($bodies[1], 'Tide:'), 'each pane names its own agent');

$cancel = curl_init('http://127.0.0.1:' . $sitePort . '/api/agent-stream');
curl_setopt_array($cancel, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => json_encode(['token' => $token, 'agent_id' => $reef['data']['agent']['id'], 'text' => 'cancel-marker']),
    CURLOPT_HTTPHEADER => ['Content-Type: application/json', 'Origin: http://127.0.0.1:' . $sitePort],
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT_MS => 250,
]);
curl_exec($cancel);
curl_close($cancel);
$saved = platform_api($sitePort, '/api/sessions', ['op' => 'get', 'session_id' => $reef['data']['agent']['chat_id']], $token);
$blob = json_encode($saved['data']['session']['messages'] ?? []);
platform_assert(!str_contains((string) $blob, 'cancel-marker'), 'a cancelled stream is not saved as a finished reply');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "agent stream tests passed\n");
