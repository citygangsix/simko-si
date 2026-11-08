<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/agents.php';
require_once __DIR__ . '/usage.php';

$body = simko_require_post_json();
$user = simko_require_user();
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
$messages[] = ['role' => 'user', 'content' => $text];
$payload = [
    'model' => $model === '' ? 'grok-4.7' : $model,
    'stream' => true,
    'messages' => $messages,
];
if (isset($cfg['stream_delay_ms'])) {
    $payload['stream_delay_ms'] = (int) $cfg['stream_delay_ms'];
}

$reply = '';
$cancelled = false;
$buffer = '';
$ch = curl_init(simko_xai_url('chat/completions'));
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => json_encode($payload),
    CURLOPT_HTTPHEADER => [
        'Content-Type: application/json',
        'Authorization: Bearer ' . simko_api_key(),
        'Accept: text/event-stream',
    ],
    CURLOPT_RETURNTRANSFER => false,
    CURLOPT_TIMEOUT => 60,
    CURLOPT_WRITEFUNCTION => static function ($curl, string $chunk) use (&$reply, &$buffer, &$cancelled): int {
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
            $delta = is_array($decoded) ? ($decoded['choices'][0]['delta']['content'] ?? '') : '';
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
curl_close($ch);

if ($cancelled || connection_aborted()) {
    echo 'data: ' . json_encode(['agent_id' => (int) $agent['id'], 'cancelled' => true]) . "\n\n";
    exit;
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
echo 'data: ' . json_encode(['agent_id' => (int) $agent['id'], 'done' => true]) . "\n\n";
