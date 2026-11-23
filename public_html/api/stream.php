<?php
declare(strict_types=1);

/**
 * Server-sent events for the main chat. The browser gets `data: {"delta": "..."}`
 * lines while Grok writes, then one `data: {"done": true, ...}` line with the same
 * fields the plain JSON reply has. Errors after the stream starts are sent as
 * `data: {"ok": false, "error": "..."}`.
 */
function simko_sse_start(): void
{
    if (headers_sent()) {
        return;
    }
    header('Content-Type: text/event-stream; charset=utf-8');
    header('Cache-Control: no-cache, no-store');
    header('X-Accel-Buffering: no');
    while (ob_get_level() > 0) {
        ob_end_flush();
    }
    @ini_set('zlib.output_compression', '0');
    @ini_set('implicit_flush', '1');
    echo ': ' . str_repeat(' ', 2048) . "\n\n";
    flush();
}

function simko_sse_send(array $event): void
{
    echo 'data: ' . json_encode($event, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n\n";
    flush();
}

/**
 * POST a streaming request to xAI and forward text deltas as they come.
 * Returns ['reply' => text, 'final' => Responses object or null, 'ticks' => cost, 'http' => code, 'aborted' => bool].
 */
function simko_stream_xai(string $endpoint, array $payload, int $timeout): array
{
    $state = ['reply' => '', 'final' => null, 'ticks' => 0, 'buffer' => '', 'aborted' => false];
    $ch = curl_init($endpoint);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode($payload, JSON_UNESCAPED_UNICODE),
        CURLOPT_HTTPHEADER => [
            'Content-Type: application/json',
            'Authorization: Bearer ' . simko_api_key(),
            'Accept: text/event-stream',
        ],
        CURLOPT_RETURNTRANSFER => false,
        CURLOPT_CONNECTTIMEOUT => 15,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_WRITEFUNCTION => static function ($curl, string $chunk) use (&$state): int {
            if (connection_aborted()) {
                $state['aborted'] = true;
                return 0;
            }
            $state['buffer'] .= $chunk;
            while (($pos = strpos($state['buffer'], "\n")) !== false) {
                $line = trim(substr($state['buffer'], 0, $pos));
                $state['buffer'] = substr($state['buffer'], $pos + 1);
                if (!str_starts_with($line, 'data:')) {
                    continue;
                }
                $json = trim(substr($line, 5));
                if ($json === '' || $json === '[DONE]') {
                    continue;
                }
                $decoded = json_decode($json, true);
                if (!is_array($decoded)) {
                    continue;
                }
                $type = (string) ($decoded['type'] ?? '');
                if ($type === 'response.completed' && is_array($decoded['response'] ?? null)) {
                    $state['final'] = $decoded['response'];
                    $state['ticks'] = (int) ($decoded['response']['usage']['cost_in_usd_ticks'] ?? $state['ticks']);
                    continue;
                }
                if (isset($decoded['usage']['cost_in_usd_ticks'])) {
                    $state['ticks'] = (int) $decoded['usage']['cost_in_usd_ticks'];
                }
                if ($type === 'response.web_search_call.in_progress' || $type === 'response.x_search_call.in_progress') {
                    simko_sse_send(['status' => 'searching']);
                    continue;
                }
                $delta = $type === 'response.output_text.delta'
                    ? ($decoded['delta'] ?? '')
                    : ($decoded['choices'][0]['delta']['content'] ?? '');
                if (!is_string($delta) || $delta === '') {
                    continue;
                }
                $state['reply'] .= $delta;
                simko_sse_send(['delta' => $delta]);
            }
            return strlen($chunk);
        },
    ]);
    curl_exec($ch);
    $http = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($http >= 400 || $http === 0) {
        simko_log_upstream($http, $err);
    }
    return ['reply' => $state['reply'], 'final' => $state['final'], 'ticks' => $state['ticks'], 'http' => $http, 'aborted' => $state['aborted']];
}
