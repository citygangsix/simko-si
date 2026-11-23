<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/agents.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/search.php';
require_once __DIR__ . '/browse.php';

$body = simko_require_post_json();
$user = simko_require_user();
simko_require_grok_user($user);
if (!simko_flag('agents')) {
    simko_fail(404, 'Side-by-side agents are turned off.');
}
$agent = simko_agent_owned((int) $user['id'], (int) ($body['agent_id'] ?? 0));
if (!$agent) {
    simko_fail(404, 'That agent is not on this account.');
}
$text = trim((string) ($body['text'] ?? ''));
if ($text === '') {
    simko_fail(400, 'Type a message for this agent.');
}
$gate = simko_usage_gate((int) $user['id']);
if (empty($gate['allowed'])) {
    simko_fail(402, 'The 5 free messages are used up.', ['paywall' => true]);
}

if (session_status() === PHP_SESSION_ACTIVE) {
    session_write_close();
}

header('Content-Type: text/event-stream; charset=utf-8');
header('Cache-Control: no-cache');
header('X-Accel-Buffering: no');
header('X-Simko-Session: closed');
while (ob_get_level() > 0) {
    ob_end_flush();
}

$cfg = simko_config();
$model = trim((string) ($cfg['model'] ?? 'grok-4.7'));
$messages = [[
    'role' => 'system',
    'content' => 'You are ' . $agent['name'] . '. ' . $agent['persona'] . ' Reply only as this agent.',
]];
foreach (simko_chat_messages((string) $agent['chat_id']) as $message) {
    $role = ($message['role'] === 'assistant' || $message['role'] === 'relay') ? 'assistant' : 'user';
    $content = trim((string) ($message['text'] ?? ''));
    if ($content !== '') {
        $messages[] = ['role' => $role, 'content' => $content];
    }
}
// Agent mode uses the same tools as chat: web and X search, the code sandbox, and pasted-link reading.
$spoken = $text;
$pages = [];
if (simko_flag('browse')) {
    foreach (simko_browse_pasted_urls($text, 2) as $url) {
        $page = simko_browse_read($url, 6000);
        $pages[] = [
            'url' => (string) $page['url'],
            'ok' => !empty($page['ok']),
            'title' => (string) ($page['title'] ?? ''),
            'chars' => !empty($page['ok']) ? simko_len((string) $page['text']) : 0,
            'error' => (string) ($page['error'] ?? ''),
        ];
        $spoken .= !empty($page['ok'])
            ? "\n\n[Text of the page at " . $page['url'] . ", fetched because the person pasted this link]\n" . $page['text'] . "\n[End of page text]"
            : "\n\n[Could not read " . $url . ': ' . $page['error'] . ']';
    }
}
$messages[] = ['role' => 'user', 'content' => $spoken];
$model = $model === '' ? 'grok-4.7' : $model;
$useTools = simko_flag('search');
$effort = simko_reasoning_effort($body['reasoning_effort'] ?? null);
if ($useTools) {
    $payload = simko_search_payload($model, $messages, false, $effort);
    $payload['stream'] = true;
    $endpoint = simko_xai_url('responses');
} else {
    $payload = [
        'model' => $model,
        'stream' => true,
        'messages' => $messages,
        'stream_options' => ['include_usage' => true],
    ];
    $endpoint = simko_xai_url('chat/completions');
}
if (isset($cfg['stream_delay_ms'])) {
    $payload['stream_delay_ms'] = (int) $cfg['stream_delay_ms'];
}

$reply = '';
$cancelled = false;
$buffer = '';
$final = null;
$costTicks = 0;
$ch = curl_init($endpoint);
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => json_encode($payload),
    CURLOPT_HTTPHEADER => [
        'Content-Type: application/json',
        'Authorization: Bearer ' . simko_api_key(),
        'Accept: text/event-stream',
    ],
    CURLOPT_RETURNTRANSFER => false,
    CURLOPT_TIMEOUT => $useTools ? 150 : 60,
    CURLOPT_WRITEFUNCTION => static function ($curl, string $chunk) use (&$reply, &$buffer, &$cancelled, &$final, &$costTicks): int {
        if (connection_aborted()) {
            $cancelled = true;
            return 0;
        }
        $buffer .= $chunk;
        while (($pos = strpos($buffer, "\n")) !== false) {
            $line = trim(substr($buffer, 0, $pos));
            $buffer = substr($buffer, $pos + 1);
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
            // Responses API stream: response.output_text.delta, then response.completed with the full response.
            $type = (string) ($decoded['type'] ?? '');
            if ($type === 'response.completed' && is_array($decoded['response'] ?? null)) {
                $final = $decoded['response'];
                $costTicks = (int) ($final['usage']['cost_in_usd_ticks'] ?? 0);
                continue;
            }
            if (isset($decoded['usage']['cost_in_usd_ticks'])) {
                $costTicks = (int) $decoded['usage']['cost_in_usd_ticks'];
            }
            $delta = $type === 'response.output_text.delta'
                ? ($decoded['delta'] ?? '')
                : ($decoded['choices'][0]['delta']['content'] ?? '');
            if (!is_string($delta) || $delta === '') {
                continue;
            }
            $reply .= $delta;
            echo 'data: ' . json_encode(['agent_id' => (int) $GLOBALS['simko_stream_agent'], 'delta' => $delta]) . "\n\n";
            flush();
        }
        return strlen($chunk);
    },
]);
$GLOBALS['simko_stream_agent'] = (int) $agent['id'];
curl_exec($ch);
$httpCode = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
$curlError = curl_error($ch);
curl_close($ch);

if ($cancelled || connection_aborted()) {
    echo 'data: ' . json_encode(['agent_id' => (int) $agent['id'], 'cancelled' => true]) . "\n\n";
    exit;
}

if ($reply === '' && is_array($final)) {
    $reply = simko_choice_text($final);
    if ($reply !== '') {
        echo 'data: ' . json_encode(['agent_id' => (int) $agent['id'], 'delta' => $reply]) . "\n\n";
    }
}

if ($reply === '') {
    $why = $curlError !== '' ? 'Grok could not be reached.' : ($httpCode >= 400 ? 'Grok returned an error (' . $httpCode . ').' : 'Grok sent an empty reply.');
    echo 'data: ' . json_encode(['agent_id' => (int) $agent['id'], 'error' => $why . ' Try again in a moment.']) . "\n\n";
}
if ($reply !== '') {
    $now = time();
    $insert = simko_db()->prepare(
        'INSERT INTO messages (chat_id, role, body, created_at) VALUES (?, ?, ?, ?)'
    );
    $insert->execute([$agent['chat_id'], 'user', $text, $now]);
    $insert->execute([$agent['chat_id'], 'assistant', $reply, $now]);
    simko_usage_record((int) $user['id'], 'message');
}
if ($costTicks > 0) {
    simko_xai_cost_note($endpoint, ['usage' => ['cost_in_usd_ticks' => $costTicks]]);
}
$done = ['agent_id' => (int) $agent['id'], 'done' => true, 'cost_ticks' => $costTicks];
if (is_array($final)) {
    $done['sources'] = simko_search_sources($final, false);
    $done['code_runs'] = simko_search_code_runs($final);
}
if ($pages !== []) {
    $done['pages'] = $pages;
}
echo 'data: ' . json_encode($done) . "\n\n";
