<?php
declare(strict_types=1);

/**
 * Function calling for chat (ASC-35). One tool list, one loop:
 *  - site tools: save_memory, list_routines, create_routine (create needs an in-chat Approve first)
 *  - Google Drive (only when connected): drive_list_picked_files, drive_read_picked_file (picked files only)
 *  - GitHub (only when connected): github_list_repos, github_read_file, github_list_issues
 *  - Google Calendar (only when connected): the calendar_* tools from calendar-tools.php
 * Tool names used in a turn are returned as tools_used so the chat can show "Used: …" chips.
 */

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/approvals.php';
require_once __DIR__ . '/recall.php';
require_once __DIR__ . '/routines.php';
require_once __DIR__ . '/connectors.php';
require_once __DIR__ . '/connector-tools.php';
require_once __DIR__ . '/calendar-tools.php';
require_once __DIR__ . '/mcp.php';
require_once __DIR__ . '/tasks.php';
require_once __DIR__ . '/paywall-switch.php';

function simko_agent_used(?string $name = null): array
{
    static $used = [];
    if ($name !== null && !in_array($name, $used, true)) {
        $used[] = $name;
    }
    return $used;
}

/** Tool schemas this person may use right now. $approvedTurn: the turn that runs an approved write (no new writes then). */
function simko_agent_schemas(int $userId, bool $isChild, bool $approvedTurn = false): array
{
    $out = [];
    if ($isChild) {
        // Child profiles keep only what they had before: Calendar when the parent connected it.
        return simko_calendar_connected($userId) ? simko_calendar_tool_schemas() : [];
    }
    if (simko_flag('memory')) {
        $out[] = ['name' => 'save_memory', 'description' => 'Save one short fact the person asked Simko SI to remember (for example "My dog is Max"). Use it when they say remember, note that, or don\'t forget.',
            'parameters' => ['type' => 'object', 'properties' => ['fact' => ['type' => 'string', 'description' => 'The fact, in the first person, under 200 characters.']], 'required' => ['fact']]];
    }
    if (simko_flag('routines')) {
        $out[] = ['name' => 'list_routines', 'description' => 'List the person\'s routines (bedtime story, Lifebook check-in, homework reminder) and their times.',
            'parameters' => ['type' => 'object', 'properties' => new stdClass()]];
        if (!$approvedTurn && simko_flag('approvals')) {
            $out[] = ['name' => 'create_routine', 'description' => 'Create a daily routine. kind is bedtime, lifebook or homework. Simko SI asks the person to approve before it is saved.',
                'parameters' => ['type' => 'object', 'properties' => [
                    'kind' => ['type' => 'string', 'enum' => ['bedtime', 'lifebook', 'homework']],
                    'hour' => ['type' => 'integer', 'description' => '0-23, local time'],
                    'minute' => ['type' => 'integer', 'description' => '0-59'],
                ], 'required' => ['kind', 'hour', 'minute']]];
        }
    }
    if (simko_flag('connectors') && simko_connector_connected($userId, 'google-drive')) {
        $out[] = ['name' => 'drive_list_picked_files', 'description' => 'List the Google Drive files the person picked for Simko SI to read. Other Drive files are not visible.',
            'parameters' => ['type' => 'object', 'properties' => new stdClass()]];
        $out[] = ['name' => 'drive_read_picked_file', 'description' => 'Read the text of one picked Google Drive file (Docs, Sheets, Slides, or a text file).',
            'parameters' => ['type' => 'object', 'properties' => ['file_id' => ['type' => 'string', 'description' => 'The id from drive_list_picked_files.']], 'required' => ['file_id']]];
    }
    if (simko_flag('connectors') && simko_connector_connected($userId, 'github')) {
        $out[] = ['name' => 'github_list_repos', 'description' => 'List the person\'s GitHub repositories, most recently updated first.',
            'parameters' => ['type' => 'object', 'properties' => new stdClass()]];
        $out[] = ['name' => 'github_read_file', 'description' => 'Read one file from a GitHub repository.',
            'parameters' => ['type' => 'object', 'properties' => [
                'repo' => ['type' => 'string', 'description' => 'owner/name'],
                'path' => ['type' => 'string'],
                'ref' => ['type' => 'string', 'description' => 'Optional branch or commit.'],
            ], 'required' => ['repo', 'path']]];
        $out[] = ['name' => 'github_list_issues', 'description' => 'List open issues in a GitHub repository.',
            'parameters' => ['type' => 'object', 'properties' => ['repo' => ['type' => 'string', 'description' => 'owner/name']], 'required' => ['repo']]];
    }
    if (simko_calendar_connected($userId)) {
        foreach (simko_calendar_tool_schemas() as $schema) {
            $out[] = $schema;
        }
    }
    // Scheduled tasks (P0): Grok can propose one; it only starts after the person's Yes on the card.
    if (!$approvedTurn && simko_flag('tasks') && simko_flag('approvals')) {
        $out[] = ['name' => 'create_task', 'description' => 'Propose a scheduled task: Grok runs the prompt on a schedule and delivers the result. Simko SI shows the person a Yes/No card; nothing starts before Yes.',
            'parameters' => ['type' => 'object', 'properties' => [
                'name' => ['type' => 'string', 'description' => 'Short name, under 80 characters.'],
                'prompt' => ['type' => 'string', 'description' => 'What Grok should do each time.'],
                'freq' => ['type' => 'string', 'enum' => ['once', 'daily', 'weekdays', 'weekly']],
                'hour' => ['type' => 'integer', 'description' => '0-23, the person\'s local time'],
                'minute' => ['type' => 'integer', 'description' => '0-59'],
                'weekday' => ['type' => 'integer', 'description' => 'For weekly: 0=Sunday .. 6=Saturday'],
                'run_date' => ['type' => 'string', 'description' => 'For once: YYYY-MM-DD'],
                'deliver_email' => ['type' => 'boolean'],
                'use_search' => ['type' => 'boolean'],
            ], 'required' => ['name', 'prompt', 'freq', 'hour', 'minute']]];
    }
    // Owner only: turning the paywall on is a Yes/No card.
    if (!$approvedTurn && simko_flag('approvals') && !simko_flag('paywall') && simko_agent_is_owner($userId)) {
        $out[] = ['name' => 'turn_paywall_on', 'description' => 'Owner only. Ask to turn the Simko SI paywall on. Simko SI shows the owner a Yes/No card with the price, free messages, Stripe mode and who is affected; nothing changes before Yes.',
            'parameters' => ['type' => 'object', 'properties' => new stdClass()]];
    }
    // MCP connector write tools (P0): each call becomes an Approve card, never runs on its own.
    foreach (simko_mcp_write_schemas($userId, $approvedTurn) as $schema) {
        $out[] = $schema;
    }
    return $out;
}

function simko_agent_is_owner(int $userId): bool
{
    $stmt = simko_db()->prepare('SELECT id, email FROM users WHERE id = ?');
    $stmt->execute([$userId]);
    return simko_is_grok_owner($stmt->fetch() ?: null);
}

function simko_agent_tools_payload(array $schemas): array
{
    $responses = [];
    $completions = [];
    foreach ($schemas as $s) {
        $responses[] = ['type' => 'function', 'name' => $s['name'], 'description' => $s['description'], 'parameters' => $s['parameters']];
        $completions[] = ['type' => 'function', 'function' => $s];
    }
    return ['responses' => $responses, 'completions' => $completions];
}

/** Light check so ordinary chats keep streaming: tools are offered when a connector is on or the message asks for a site tool. */
function simko_agent_wants_tools(int $userId, string $text, bool $isChild): bool
{
    if ($isChild) {
        return false;
    }
    if (simko_flag('connectors') && (simko_connector_connected($userId, 'google-drive') || simko_connector_connected($userId, 'github'))) {
        return true;
    }
    if (simko_mcp_write_schemas($userId) !== []) {
        return true;
    }
    if (simko_flag('approvals') && simko_flag('tasks') && preg_match('/\b(schedul\w*|every (day|morning|evening|night|week\w*|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|each (day|morning|week)|daily|weekly|weekdays|tasks?)\b/i', $text)) {
        return true;
    }
    if (simko_flag('approvals') && preg_match('/\bpaywall\b/i', $text) && simko_agent_is_owner($userId)) {
        return true;
    }
    return (bool) preg_match('/\b(remember|don\'?t forget|note that|routines?|remind(er)?s?|bedtime|homework|lifebook|check-?in)\b/i', $text);
}

function simko_agent_system_note(array $schemas): string
{
    $names = array_column($schemas, 'name');
    $bits = ['You can call tools. Use one only when it helps, then answer from its result in plain English.'];
    if (in_array('save_memory', $names, true)) {
        $bits[] = 'When the person asks you to remember something, call save_memory with the fact.';
    }
    if (in_array('create_routine', $names, true)) {
        $bits[] = 'When they ask for a routine or daily reminder, call create_routine; Simko SI shows them an Approve button before it is saved.';
    }
    if (in_array('create_task', $names, true)) {
        $bits[] = 'When they ask for something to happen on a schedule (every morning, each Friday), call create_task; Simko SI shows them a Yes/No card and nothing starts before Yes.';
    }
    if (in_array('turn_paywall_on', $names, true)) {
        $bits[] = 'When the owner asks to turn the paywall on, call turn_paywall_on; Simko SI shows a Yes/No card.';
    }
    if (in_array('drive_list_picked_files', $names, true)) {
        $bits[] = 'Google Drive is connected: you can only see files the person picked. If a file is not there, ask them to pick it with "Pick files" in Connectors.';
    }
    if (in_array('github_list_repos', $names, true)) {
        $bits[] = 'GitHub is connected (read only).';
    }
    foreach ($names as $n) {
        if (str_starts_with((string) $n, 'mcp_')) {
            $bits[] = 'Tools named mcp_* belong to the person\'s connected MCP servers and change something there; Simko SI shows an Approve button before any of them runs.';
            break;
        }
    }
    return implode(' ', $bits);
}

function simko_agent_save_memory(int $userId, array $args): array
{
    if (!simko_flag('memory')) {
        return ['ok' => false, 'error' => 'Memory is turned off.'];
    }
    $fact = trim((string) preg_replace('/\s+/', ' ', (string) ($args['fact'] ?? '')));
    if ($fact === '' || simko_len($fact) > 200) {
        return ['ok' => false, 'error' => 'Give one short fact under 200 characters.'];
    }
    $exists = simko_db()->prepare('SELECT id FROM memories WHERE user_id = ? AND child_profile_id IS NULL AND lower(fact) = lower(?)');
    $exists->execute([$userId, $fact]);
    if ($exists->fetch()) {
        return ['ok' => true, 'saved' => false, 'note' => 'Already remembered.', 'fact' => $fact];
    }
    $count = simko_db()->prepare('SELECT COUNT(*) FROM memories WHERE user_id = ?');
    $count->execute([$userId]);
    if ((int) $count->fetchColumn() >= 200) {
        return ['ok' => false, 'error' => 'Memory is full. Delete some in the Memory panel first.'];
    }
    simko_db()->prepare('INSERT INTO memories (user_id, child_profile_id, fact, created_at) VALUES (?, NULL, ?, ?)')->execute([$userId, $fact, time()]);
    return ['ok' => true, 'saved' => true, 'fact' => $fact];
}

function simko_agent_routine_args(array $args): ?array
{
    $kind = (string) ($args['kind'] ?? '');
    $hour = filter_var($args['hour'] ?? null, FILTER_VALIDATE_INT);
    $minute = filter_var($args['minute'] ?? null, FILTER_VALIDATE_INT);
    if (!isset(simko_routine_kinds()[$kind]) || $hour === false || $minute === false || $hour < 0 || $hour > 23 || $minute < 0 || $minute > 59) {
        return null;
    }
    return ['kind' => $kind, 'hour' => $hour, 'minute' => $minute, 'tz' => (string) ($args['tz'] ?? '')];
}

function simko_agent_routine_summary(array $a): string
{
    return 'Create routine: ' . simko_routine_kinds()[$a['kind']] . ' daily at ' . sprintf('%02d:%02d', $a['hour'], $a['minute']);
}

/** Runs one tool. A write that needs approval stops the request here with an approval for the chat to show. */
function simko_agent_run_tool(int $userId, string $name, array $args, array $body, array $allowed): array
{
    if (!in_array($name, $allowed, true)) {
        return ['ok' => false, 'error' => 'That tool is not available right now.'];
    }
    simko_agent_used($name);
    switch ($name) {
        case 'save_memory':
            return simko_agent_save_memory($userId, $args);
        case 'list_routines':
            return ['ok' => true, 'routines' => simko_routine_rows($userId)];
        case 'create_routine':
            $a = simko_agent_routine_args($args);
            if ($a === null) {
                return ['ok' => false, 'error' => 'Pick bedtime, lifebook or homework, an hour 0-23 and a minute 0-59.'];
            }
            $a['tz'] = (string) ($body['tz'] ?? '');
            // Never runs here: it waits for the person to press Approve in the chat.
            simko_guard_approval($userId, [], 'routine-create', simko_agent_routine_summary($a), ['tool' => 'create_routine', 'arguments' => $a]);
            return ['ok' => false, 'error' => 'Approvals are off.'];
        case 'create_task':
            $t = [
                'name' => (string) ($args['name'] ?? ''), 'prompt' => (string) ($args['prompt'] ?? ''), 'freq' => (string) ($args['freq'] ?? 'daily'),
                'hour' => (int) ($args['hour'] ?? -1), 'minute' => (int) ($args['minute'] ?? -1), 'weekday' => (int) ($args['weekday'] ?? 1),
                'run_date' => (string) ($args['run_date'] ?? ''), 'tz' => (string) ($body['tz'] ?? ''),
                'deliver_email' => !empty($args['deliver_email']), 'use_search' => !empty($args['use_search']),
            ];
            $checked = simko_task_validate($t, time());
            if (isset($checked['error'])) {
                return ['ok' => false, 'error' => $checked['error']];
            }
            simko_tasks_migrate();
            $count = simko_db()->prepare('SELECT COUNT(*) FROM tasks WHERE user_id = ?');
            $count->execute([$userId]);
            if ((int) $count->fetchColumn() >= simko_tasks_limits()['max_per_user']) {
                return ['ok' => false, 'error' => 'The scheduled task limit is reached. The person must delete one first.'];
            }
            $row = $checked['row'];
            $facts = simko_task_card_facts($row, 'create');
            // Never saved or started here: it waits for the person's Yes on the card.
            simko_guard_approval($userId, [], 'task-start', $facts['title'], ['mode' => 'create', 'task' => $row], $facts);
            return ['ok' => false, 'error' => 'Approvals are off.'];
        case 'turn_paywall_on':
            $owner = simko_db()->prepare('SELECT * FROM users WHERE id = ?');
            $owner->execute([$userId]);
            $ownerRow = $owner->fetch() ?: null;
            if (!simko_is_grok_owner($ownerRow) || simko_flag('paywall')) {
                return ['ok' => false, 'error' => simko_flag('paywall') ? 'The paywall is already on.' : 'Only the owner can do that.'];
            }
            simko_ok(['approval' => simko_paywall_request_on($ownerRow)]);
            return ['ok' => false];
        case 'drive_list_picked_files':
            return ['ok' => true, 'files' => simko_drive_picks($userId)];
        case 'drive_read_picked_file':
            return simko_drive_read($userId, (string) ($args['file_id'] ?? ''));
        case 'github_list_repos':
            return simko_github_list_repos($userId);
        case 'github_read_file':
            return simko_github_read_file($userId, (string) ($args['repo'] ?? ''), (string) ($args['path'] ?? ''), (string) ($args['ref'] ?? ''));
        case 'github_list_issues':
            return simko_github_list_issues($userId, (string) ($args['repo'] ?? ''));
    }
    if (str_starts_with($name, 'calendar_')) {
        return simko_calendar_run_tool($userId, $name, $args, $body);
    }
    if (str_starts_with($name, 'mcp_')) {
        return simko_mcp_run_tool($userId, $name, $args);
    }
    return ['ok' => false, 'error' => 'Unknown tool.'];
}

/** On the turn after Approve: runs an approved routine once. Returns a note for the system prompt. */
function simko_agent_apply_approved(int $userId, array $body): string
{
    $approvalId = (int) ($body['approval_id'] ?? 0);
    if ($approvalId < 1) {
        return '';
    }
    $stmt = simko_db()->prepare('SELECT action, payload, status FROM approvals WHERE id = ? AND user_id = ?');
    $stmt->execute([$approvalId, $userId]);
    $row = $stmt->fetch();
    if (!$row || (string) $row['action'] !== 'routine-create' || (string) $row['status'] !== 'approved') {
        return '';
    }
    $done = simko_db()->prepare('SELECT 1 FROM audit_log WHERE user_id = ? AND action = ? AND summary LIKE ? LIMIT 1');
    $done->execute([$userId, 'routine-ran', 'Ran approval ' . $approvalId . ':%']);
    if ($done->fetch()) {
        return 'Routine action result: that routine was already created earlier.';
    }
    $payload = json_decode((string) $row['payload'], true);
    $a = simko_agent_routine_args(is_array($payload['arguments'] ?? null) ? $payload['arguments'] : []);
    if ($a === null) {
        return '';
    }
    $saved = simko_routine_save($userId, $a);
    simko_audit($userId, 'routine-ran', 'Ran approval ' . $approvalId . ': ' . simko_agent_routine_summary($a));
    simko_agent_used('create_routine');
    return 'Routine action result: the person approved, and Simko SI created ' . json_encode($saved, JSON_UNESCAPED_UNICODE)
        . '. Tell them it is saved and when it runs. Do not ask to create it again.';
}

function simko_agent_args(mixed $raw): array
{
    if (is_array($raw)) {
        return $raw;
    }
    $d = is_string($raw) && $raw !== '' ? json_decode($raw, true) : null;
    return is_array($d) ? $d : [];
}

function simko_agent_collect(array $data, array $allowed): array
{
    $calls = [];
    $message = $data['choices'][0]['message'] ?? null;
    if (is_array($message) && is_array($message['tool_calls'] ?? null)) {
        foreach ($message['tool_calls'] as $c) {
            $fn = is_array($c['function'] ?? null) ? $c['function'] : [];
            $calls[] = ['id' => (string) ($c['id'] ?? ''), 'name' => (string) ($fn['name'] ?? ''), 'arguments' => simko_agent_args($fn['arguments'] ?? [])];
        }
    }
    foreach ((array) ($data['output'] ?? []) as $item) {
        if (is_array($item) && ($item['type'] ?? '') === 'function_call') {
            $calls[] = ['id' => (string) ($item['call_id'] ?? $item['id'] ?? ''), 'name' => (string) ($item['name'] ?? ''), 'arguments' => simko_agent_args($item['arguments'] ?? []), 'raw' => $item];
        }
    }
    return $calls;
}

function simko_agent_tool_loop(int $userId, array $body, string $url, array $payload, int $timeout, string $style, array $allowed): array
{
    $data = simko_curl_json($url, $payload, $timeout);
    for ($round = 0; $round < 4; $round++) {
        $calls = simko_agent_collect($data, $allowed);
        if ($calls === []) {
            break;
        }
        if ($style === 'completions') {
            $payload['messages'][] = $data['choices'][0]['message'];
        }
        foreach ($calls as $call) {
            $out = json_encode(simko_agent_run_tool($userId, $call['name'], $call['arguments'], $body, $allowed), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
            if ($style === 'completions') {
                $payload['messages'][] = ['role' => 'tool', 'tool_call_id' => $call['id'], 'content' => $out];
            } else {
                if (isset($call['raw'])) {
                    $payload['input'][] = $call['raw'];
                }
                $payload['input'][] = ['type' => 'function_call_output', 'call_id' => $call['id'], 'output' => $out];
            }
        }
        $data = simko_curl_json($url, $payload, $timeout);
    }
    return $data;
}
