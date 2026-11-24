<?php
declare(strict_types=1);

// Scripted xAI for function-calling tests (Responses + chat completions). Logs each request body to SIMKO_XAI_LOG.
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$body = json_decode(file_get_contents('php://input') ?: '', true) ?: [];
$log = (string) getenv('SIMKO_XAI_LOG');
if ($log !== '') {
    file_put_contents($log, json_encode(['path' => $path, 'body' => $body]) . "\n", FILE_APPEND);
}
header('Content-Type: application/json');
$responses = $path === '/v1/responses';
$items = $responses ? ($body['input'] ?? []) : ($body['messages'] ?? []);
$offered = [];
foreach ($body['tools'] ?? [] as $t) {
    $n = (string) ($t['name'] ?? ($t['function']['name'] ?? ''));
    if ($n !== '') {
        $offered[] = $n;
    }
}
$user = '';
$outputs = [];
foreach ($items as $m) {
    if (!is_array($m)) {
        continue;
    }
    if (($m['role'] ?? '') === 'user') {
        $user = is_string($m['content'] ?? null) ? $m['content'] : json_encode($m['content'] ?? '');
    }
    if (($m['type'] ?? '') === 'function_call_output') {
        $outputs[] = (string) $m['output'];
    }
    if (($m['role'] ?? '') === 'tool') {
        $outputs[] = (string) $m['content'];
    }
}
$system = json_encode($items[0] ?? []);
$reply = static function (string $text) use ($responses): void {
    echo json_encode($responses
        ? ['id' => 'r', 'output_text' => $text, 'output' => [['type' => 'message', 'role' => 'assistant', 'content' => [['type' => 'output_text', 'text' => $text]]]], 'usage' => ['cost_in_usd_ticks' => 1000]]
        : ['id' => 'c', 'choices' => [['message' => ['role' => 'assistant', 'content' => $text]]], 'usage' => ['cost_in_usd_ticks' => 1000]]);
};
$call = static function (string $name, array $args) use ($responses): void {
    $id = 'call-' . $name;
    echo json_encode($responses
        ? ['id' => 'r', 'output' => [['type' => 'function_call', 'call_id' => $id, 'name' => $name, 'arguments' => json_encode($args)]], 'usage' => ['cost_in_usd_ticks' => 1000]]
        : ['id' => 'c', 'choices' => [['message' => ['role' => 'assistant', 'content' => null, 'tool_calls' => [['id' => $id, 'type' => 'function', 'function' => ['name' => $name, 'arguments' => json_encode($args)]]]]]], 'usage' => ['cost_in_usd_ticks' => 1000]]);
};
$u = strtolower($user);
if ($outputs !== []) {
    $last = end($outputs);
    if (str_contains($u, 'read my trip plan') && count($outputs) === 1 && in_array('drive_read_picked_file', $offered, true)) {
        $call('drive_read_picked_file', ['file_id' => 'doc1234567890']);
        return true;
    }
    $reply('Tool said: ' . substr($last, 0, 400));
    return true;
}
if (str_contains($system, 'Routine action result') && str_contains($u, 'sneak')) {
    $call('create_routine', ['kind' => 'bedtime', 'hour' => 20, 'minute' => 0]);
    return true;
}
if (str_contains($system, 'Routine action result')) {
    $reply('Your routine is saved. [offered:' . implode(',', $offered) . ']');
    return true;
}
$want = null;
if (str_contains($u, 'remember that my dog is max')) {
    $want = ['save_memory', ['fact' => 'My dog is Max']];
} elseif (str_contains($u, 'homework routine')) {
    $want = ['create_routine', ['kind' => 'homework', 'hour' => 19, 'minute' => 30]];
} elseif (str_contains($u, 'what routines')) {
    $want = ['list_routines', []];
} elseif (str_contains($u, 'read my trip plan')) {
    $want = ['drive_list_picked_files', []];
} elseif (str_contains($u, 'my repos')) {
    $want = ['github_list_repos', []];
}
if ($want !== null && in_array($want[0], $offered, true)) {
    $call($want[0], $want[1]);
    return true;
}
$reply('Plain reply. [offered:' . implode(',', $offered) . '] [stream:' . (!empty($body['stream']) ? 'yes' : 'no') . ']');
return true;
