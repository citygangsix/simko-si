<?php
declare(strict_types=1);

/**
 * One real xAI web_search call against the patched helpers.
 * Usage: XAI_API_KEY=... php tests/live-search-harness.php
 * Does not print the key. Does not toggle flags or deploy.
 */

require __DIR__ . '/platform-support.php';

$key = getenv('XAI_API_KEY');
if (!is_string($key) || trim($key) === '') {
    fwrite(STDERR, "Set XAI_API_KEY in the environment first.\n");
    exit(2);
}
$key = trim($key);

$private = platform_private('live-search', ['search' => true], [
    'xai_api_key' => $key,
    'xai_base_url' => 'https://api.x.ai/v1',
    'timeout_seconds' => 90,
]);
putenv('SIMKOSI_PRIVATE=' . $private);
$_ENV['SIMKOSI_PRIVATE'] = $private;

require_once $GLOBALS['simko_root'] . '/public_html/api/search.php';

$query = 'Where do loggerhead sea turtles nest in Florida?';
$payload = simko_search_payload('grok-4.7', [
    ['role' => 'system', 'content' => 'You are Simko SI. Reply in clear everyday English. Be warm and brief. Cite only facts from the web sources.'],
    ['role' => 'user', 'content' => $query],
], false);

$started = microtime(true);
$data = simko_curl_json(simko_xai_url('responses'), $payload, 90);
$elapsed = (int) round(microtime(true) - $started);
$reply = simko_choice_text($data);
$sources = simko_search_sources($data, false);

if ($reply === '') {
    fwrite(STDERR, "FAIL no reply text came back from /v1/responses\n");
    exit(1);
}
if ($sources === []) {
    fwrite(STDERR, "FAIL reply came back but sources was empty\n");
    fwrite(STDERR, "status=" . (string) ($data['status'] ?? '') . "\n");
    exit(1);
}

$usage = $data['usage'] ?? [];
$toolUsage = $usage['server_side_tool_usage'] ?? $usage['server_side_tool_usage_details'] ?? [];

fwrite(STDOUT, "query: {$query}\n");
fwrite(STDOUT, "elapsed_seconds: {$elapsed}\n");
fwrite(STDOUT, "status: " . (string) ($data['status'] ?? 'unknown') . "\n");
fwrite(STDOUT, "model: " . (string) ($data['model'] ?? 'unknown') . "\n");
fwrite(STDOUT, "reply_chars: " . strlen($reply) . "\n");
fwrite(STDOUT, "reply_preview: " . simko_clip(preg_replace('/\s+/', ' ', $reply) ?? $reply, 280) . "\n");
fwrite(STDOUT, "sources_count: " . count($sources) . "\n");
foreach ($sources as $i => $url) {
    fwrite(STDOUT, "source_" . ($i + 1) . ": {$url}\n");
}
if (is_array($toolUsage) && $toolUsage !== []) {
    fwrite(STDOUT, "tool_usage: " . json_encode($toolUsage) . "\n");
}
if (isset($usage['input_tokens']) || isset($usage['prompt_tokens']) || isset($usage['total_tokens'])) {
    fwrite(STDOUT, "tokens: " . json_encode([
        'input' => $usage['input_tokens'] ?? $usage['prompt_tokens'] ?? null,
        'output' => $usage['output_tokens'] ?? $usage['completion_tokens'] ?? null,
        'total' => $usage['total_tokens'] ?? null,
        'reasoning' => $usage['reasoning_tokens'] ?? ($usage['output_tokens_details']['reasoning_tokens'] ?? null),
    ]) . "\n");
}
fwrite(STDOUT, "live search harness passed\n");
