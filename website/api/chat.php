<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/search.php';
require_once __DIR__ . '/recall.php';

$body = simko_require_post_json();
$user = simko_require_user();
$text = trim((string) ($body['text'] ?? ''));
if ($text === '') {
    simko_fail(400, 'Type a message, then Send.');
}
$max = simko_max_chars();
if (simko_len($text) > $max) {
    simko_fail(413, 'That message is too long. Keep it under ' . $max . ' characters.');
}

$gate = simko_usage_gate((int) $user['id']);
if (empty($gate['allowed'])) {
    simko_fail(402, 'The 5 free messages are used up.', [
        'paywall' => true,
        'used' => $gate['used'] ?? 0,
        'limit' => $gate['limit'] ?? 5,
    ]);
}

$feature = strtolower((string) ($body['feature'] ?? ''));
$allowedFeatures = ['div', 'mul_multi', 'decimal', 'sub', 'add', 'mul', 'fe_shell'];
if (!in_array($feature, $allowedFeatures, true)) {
    $feature = '';
}

$cfg = simko_config();
$model = trim((string) ($cfg['model'] ?? 'grok-4.7'));
if ($model === '') {
    $model = 'grok-4.7';
}
$system = trim((string) ($cfg['system_prompt'] ?? ''));
if ($system === '') {
    $system = 'You are Simko SI, Joseph Simko\'s assistant. Reply in clear everyday English. Be warm and brief.';
}

$memoryChild = null;
if (simko_flag('memory') && !empty($body['child_id'])) {
    $memoryChild = simko_requested_child((int) $user['id'], $body);
}
$remembered = simko_memory_prompt((int) $user['id'], $memoryChild);
if ($remembered !== '') {
    $system .= "\n\n" . $remembered;
}
$messages = [['role' => 'system', 'content' => $system]];
$sessionId = (string) ($body['session_id'] ?? '');
$chat = simko_chat_owned((int) $user['id'], $sessionId);
if ($chat) {
    foreach (simko_chat_messages($chat['id']) as $message) {
        $role = ($message['role'] === 'assistant' || $message['role'] === 'relay') ? 'assistant' : 'user';
        $content = trim((string) $message['text']);
        if ($content === '') {
            continue;
        }
        $messages[] = ['role' => $role, 'content' => $content];
    }
}
$spoken = $text;
if ($feature !== '') {
    $spoken .= "\n\nThe person is on a " . $feature . " step. Answer in everyday words.";
}
$strictSearch = false;
if (simko_flag('search') && !empty($body['child_id'])) {
    simko_requested_child((int) $user['id'], $body);
    $strictSearch = true;
}
if (simko_flag('search') && simko_search_blocked($text, $strictSearch)) {
    simko_fail(400, $strictSearch
        ? 'That search is blocked for a child profile.'
        : 'That search is blocked.');
}

$messages[] = ['role' => 'user', 'content' => $spoken];
if (count($messages) > 41) {
    $messages = array_merge([$messages[0]], array_slice($messages, -40));
}

$timeout = (int) ($cfg['timeout_seconds'] ?? 45);
if ($timeout < 5) {
    $timeout = 45;
}
@set_time_limit($timeout + 5);

$completion = [
    'model' => $model,
    'stream' => false,
    'messages' => $messages,
];
if (simko_flag('search')) {
    $completion['search_parameters'] = simko_search_parameters($strictSearch);
}
$data = simko_curl_json(simko_xai_url('chat/completions'), $completion, $timeout);
$reply = simko_choice_text($data);
if ($reply === '') {
    simko_fail(502, 'No reply came back from Simko SI. Try again in a moment.');
}

simko_usage_record((int) $user['id'], !empty($body['voice']) ? 'voice' : 'message');
simko_memory_learn((int) $user['id'], $memoryChild, $text);

simko_ok([
    'everyday' => $reply,
    'raw' => '',
    'model' => $model,
    'intent' => $feature === '' ? 'chat' : $feature,
    'usage' => simko_flag('paywall') ? simko_usage_snapshot((int) $user['id']) : null,
    'sources' => simko_flag('search') ? simko_search_sources($data, $strictSearch) : [],
]);
