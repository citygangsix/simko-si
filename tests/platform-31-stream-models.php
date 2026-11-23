<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Main chat streams text as server-sent events, and the model picker only accepts listed models.
$bodies = sys_get_temp_dir() . '/simko-stream-bodies-' . getmypid() . '.log';
@unlink($bodies);
putenv('MOCK_XAI_BODIES=' . $bodies);
[$mock, $mockPipes] = platform_mock(8872);
@unlink($bodies);
foreach ([['plain', false, 8873], ['search', true, 8870]] as [$name, $search, $port]) {
    $private = platform_private('stream-' . $name, ['search' => $search, 'paywall' => false], ['xai_base_url' => 'http://127.0.0.1:8872/v1']);
    [$site, $sitePipes] = platform_site($private, $port);
    $u = platform_signup($port, 'stream-' . $name . '-' . getmypid() . '@simkosi.test');
    $ctx = stream_context_create(['http' => [
        'method' => 'POST',
        'header' => "Content-Type: application/json\r\nAccept: text/event-stream\r\nOrigin: http://127.0.0.1:{$port}\r\nAuthorization: Bearer {$u['token']}\r\n",
        'content' => json_encode(['text' => 'Say hi', 'stream' => true, 'model' => 'grok-4.3']),
        'ignore_errors' => true,
        'timeout' => 30,
    ]]);
    $raw = (string) file_get_contents('http://127.0.0.1:' . $port . '/api/simco/turn', false, $ctx);
    $type = '';
    foreach ($http_response_header ?? [] as $h) {
        if (stripos($h, 'Content-Type:') === 0) {
            $type = $h;
        }
    }
    platform_assert(str_contains($type, 'text/event-stream'), $name . ': reply is a stream');
    $deltas = '';
    $done = null;
    foreach (explode("\n", $raw) as $line) {
        if (!str_starts_with($line, 'data:')) {
            continue;
        }
        $ev = json_decode(trim(substr($line, 5)), true);
        if (isset($ev['delta'])) {
            $deltas .= $ev['delta'];
        } elseif (!empty($ev['done'])) {
            $done = $ev;
        }
    }
    platform_assert($deltas !== '', $name . ': text arrives in pieces');
    platform_assert(is_array($done) && ($done['everyday'] ?? '') === $deltas, $name . ': the final event carries the same full reply');
    platform_assert(($done['model'] ?? '') === 'grok-4.3', $name . ': the picked model is used');
    $sent = (string) @file_get_contents($bodies);
    platform_assert(str_contains($sent, '"model":"grok-4.3"') && str_contains($sent, '"stream":true'), $name . ': xAI got the picked model with streaming on');
    @unlink($bodies);
    $bad = platform_api($port, '/api/simco/turn', ['text' => 'Say hi', 'model' => 'gpt-evil'], $u['token']);
    platform_assert($bad['status'] === 200 && ($bad['data']['model'] ?? '') === 'grok-4.7', $name . ': an unlisted model falls back to the default');
    $plain = platform_api($port, '/api/simco/turn', ['text' => 'Say hi'], $u['token']);
    platform_assert($plain['status'] === 200 && ($plain['data']['everyday'] ?? '') !== '', $name . ': plain JSON replies still work');
    $models = platform_api($port, '/api/platform', ['op' => 'models'], $u['token']);
    platform_assert(count($models['data']['models'] ?? []) >= 2 && ($models['data']['spend']['cap_usd'] ?? null) == 5, $name . ': models list and today\'s spend for the owner');
    platform_stop($site, $sitePipes);
}
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "stream and model tests passed\n");
