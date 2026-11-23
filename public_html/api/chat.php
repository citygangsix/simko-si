<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/search.php';
require_once __DIR__ . '/recall.php';
require_once __DIR__ . '/browse.php';
require_once __DIR__ . '/files.php';

$body = simko_require_post_json();
$user = simko_require_user();
simko_require_grok_owner($user);
$text = trim((string) ($body['text'] ?? ''));
// Paperclip: one picture (Grok vision) or one PDF/text file (read here for Q&A).
$file = isset($body['file']) && $body['file'] !== null ? simko_attachment_read($body['file']) : null;
if ($text === '' && $file !== null) {
    $text = $file['kind'] === 'image' ? 'What is in this picture?' : 'Summarize this file in a few lines.';
}
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

// Page reading: only links the owner pasted into this message, never links found on a page.
$pages = [];
if (simko_flag('browse') && empty($body['child_id'])) {
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
            ? "\n\n[Text of the page at " . $page['url'] . ", fetched by Simko SI because the person pasted this link"
                . (($page['title'] ?? '') !== '' ? ' (title: ' . $page['title'] . ')' : '') . "]\n" . $page['text'] . "\n[End of page text]"
            : "\n\n[Simko SI could not read " . $url . ': ' . $page['error'] . ']';
    }
}
$effort = simko_reasoning_effort($body['reasoning_effort'] ?? null);
if ($file !== null) {
    $spoken .= simko_attach_prompt($file);
}
// DeepSearch: several web and X searches, cross-checked, with a sources list.
$deep = !empty($body['deep_search']) && simko_flag('search') && !$strictSearch;
if ($deep) {
    $messages[0]['content'] .= "\n\n" . simko_deep_search_instructions();
    if ($effort === null) {
        $effort = 'high';
    }
}

$messages[] = ['role' => 'user', 'content' => simko_flag('search')
    ? simko_attach_responses_content($spoken, $file)
    : simko_attach_chat_content($spoken, $file)];
if (count($messages) > 41) {
    $messages = array_merge([$messages[0]], array_slice($messages, -40));
}

$timeout = (int) ($cfg['timeout_seconds'] ?? 45);
if ($timeout < 5) {
    $timeout = 45;
}
// Agentic web_search on the Responses API can take a few extra steps.
if (simko_flag('search') && $timeout < 90) {
    $timeout = 90;
}
if ($deep && $timeout < 240) {
    $timeout = 240;
}
@set_time_limit($timeout + 5);

if (simko_flag('search')) {
    $data = simko_curl_json(
        simko_xai_url('responses'),
        simko_search_payload($model, $messages, $strictSearch, $effort, $deep),
        $timeout
    );
} else {
    $completion = [
        'model' => $model,
        'stream' => false,
        'messages' => $messages,
    ];
    if ($effort !== null) {
        $completion['reasoning_effort'] = $effort;
    }
    $data = simko_curl_json(simko_xai_url('chat/completions'), $completion, $timeout);
}
$reply = simko_choice_text($data);
if ($reply === '') {
    simko_fail(502, 'No reply came back from Simko SI. Try again in a moment.');
}

simko_usage_record((int) $user['id'], !empty($body['voice']) ? 'voice' : 'message');
simko_memory_learn((int) $user['id'], $memoryChild, $text);

$payload = [
    'everyday' => $reply,
    'raw' => '',
    'model' => $model,
    'intent' => $feature === '' ? 'chat' : $feature,
    'usage' => simko_flag('paywall') ? simko_usage_snapshot((int) $user['id']) : null,
];
if (simko_flag('search')) {
    $payload['sources'] = simko_search_sources($data, $strictSearch);
    $payload['code_runs'] = simko_search_code_runs($data);
}
if ($pages !== []) {
    $payload['pages'] = $pages;
}
if ($file !== null) {
    $payload['attachment'] = simko_attach_summary($file);
}
if ($deep) {
    $payload['deep_search'] = true;
    $payload['search_calls'] = simko_search_call_count($data);
}
$payload['cost_ticks'] = simko_xai_cost_total();
$payload['reasoning_effort'] = $effort ?? 'default';
simko_ok($payload);
