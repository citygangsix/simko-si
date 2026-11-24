<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/approvals.php';
require_once __DIR__ . '/connectors.php';

function simko_calendar_provider(): string
{
    return 'google-calendar';
}

function simko_calendar_connected(int $userId): bool
{
    if (!simko_flag('connectors') || $userId < 1) {
        return false;
    }
    $stmt = simko_db()->prepare('SELECT 1 FROM connector_grants WHERE user_id = ? AND provider = ?');
    $stmt->execute([$userId, simko_calendar_provider()]);
    return (bool) $stmt->fetch();
}

// simko_connector_access_token() lives in connectors.php (shared by Drive, GitHub and Calendar).

function simko_calendar_http(int $userId, string $method, string $url, ?array $json = null): array
{
    $token = simko_connector_access_token($userId, simko_calendar_provider());
    $ch = curl_init($url);
    $headers = [
        'Authorization: Bearer ' . $token,
        'Accept: application/json',
    ];
    $opts = [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 20,
    ];
    if ($json !== null) {
        $headers[] = 'Content-Type: application/json';
        $opts[CURLOPT_POSTFIELDS] = json_encode($json, JSON_UNESCAPED_UNICODE);
    }
    $opts[CURLOPT_HTTPHEADER] = $headers;
    curl_setopt_array($ch, $opts);
    $raw = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    $data = is_string($raw) ? json_decode($raw, true) : null;
    if ($code >= 400 || ($method !== 'DELETE' && !is_array($data) && $code !== 204)) {
        $message = is_array($data) ? (string) ($data['error']['message'] ?? $data['error'] ?? 'Calendar request failed.') : 'Calendar request failed.';
        return ['ok' => false, 'error' => $message, 'status' => $code];
    }
    if ($method === 'DELETE' || $code === 204) {
        return ['ok' => true, 'deleted' => true];
    }
    return ['ok' => true, 'data' => is_array($data) ? $data : []];
}

function simko_calendar_api_base(): string
{
    $cfg = simko_config_or_empty();
    $base = trim((string) (($cfg['connectors']['google-calendar']['api_base'] ?? '')));
    return $base !== '' ? rtrim($base, '/') : 'https://www.googleapis.com/calendar/v3';
}

function simko_calendar_when(array $when): array
{
    $date = trim((string) ($when['date'] ?? ''));
    $dateTime = trim((string) ($when['dateTime'] ?? $when['date_time'] ?? $when['datetime'] ?? ''));
    $timeZone = trim((string) ($when['timeZone'] ?? $when['time_zone'] ?? 'America/New_York'));
    if ($date !== '') {
        return ['date' => $date];
    }
    if ($dateTime !== '') {
        $row = ['dateTime' => $dateTime];
        if ($timeZone !== '') {
            $row['timeZone'] = $timeZone;
        }
        return $row;
    }
    if (isset($when[0]) || is_string($when ?? null)) {
        $raw = is_string($when) ? $when : '';
        if ($raw !== '') {
            return str_contains($raw, 'T') ? ['dateTime' => $raw, 'timeZone' => $timeZone] : ['date' => $raw];
        }
    }
    return [];
}

function simko_calendar_list(int $userId, array $args): array
{
    $zone = new DateTimeZone(trim((string) ($args['time_zone'] ?? 'America/New_York')) ?: 'America/New_York');
    $start = trim((string) ($args['time_min'] ?? ''));
    $end = trim((string) ($args['time_max'] ?? ''));
    if ($start === '') {
        $now = new DateTimeImmutable('now', $zone);
        $start = $now->modify('monday this week')->setTime(0, 0, 0)->format(DateTimeInterface::ATOM);
    }
    if ($end === '') {
        $from = new DateTimeImmutable($start);
        $end = $from->modify('+7 days')->format(DateTimeInterface::ATOM);
    }
    $query = [
        'timeMin' => $start,
        'timeMax' => $end,
        'singleEvents' => 'true',
        'orderBy' => 'startTime',
        'maxResults' => min(40, max(1, (int) ($args['max_results'] ?? 20))),
    ];
    $q = trim((string) ($args['query'] ?? ''));
    if ($q !== '') {
        $query['q'] = $q;
    }
    $url = simko_calendar_api_base() . '/calendars/primary/events?' . http_build_query($query);
    $res = simko_calendar_http($userId, 'GET', $url);
    if (empty($res['ok'])) {
        return $res;
    }
    $events = [];
    foreach ((array) (($res['data']['items'] ?? [])) as $item) {
        if (!is_array($item)) {
            continue;
        }
        $events[] = [
            'id' => (string) ($item['id'] ?? ''),
            'summary' => (string) ($item['summary'] ?? '(no title)'),
            'start' => $item['start']['dateTime'] ?? $item['start']['date'] ?? '',
            'end' => $item['end']['dateTime'] ?? $item['end']['date'] ?? '',
            'location' => (string) ($item['location'] ?? ''),
            'description' => simko_clip((string) ($item['description'] ?? ''), 400),
        ];
    }
    return ['ok' => true, 'events' => $events, 'time_min' => $start, 'time_max' => $end];
}

function simko_calendar_create(int $userId, array $args): array
{
    $summary = trim((string) ($args['summary'] ?? ''));
    $start = simko_calendar_when(is_array($args['start'] ?? null) ? $args['start'] : ['dateTime' => (string) ($args['start'] ?? '')]);
    $end = simko_calendar_when(is_array($args['end'] ?? null) ? $args['end'] : ['dateTime' => (string) ($args['end'] ?? '')]);
    if ($summary === '' || $start === [] || $end === []) {
        return ['ok' => false, 'error' => 'A title, start, and end are required to create an event.'];
    }
    $body = ['summary' => $summary, 'start' => $start, 'end' => $end];
    $desc = trim((string) ($args['description'] ?? ''));
    $loc = trim((string) ($args['location'] ?? ''));
    if ($desc !== '') {
        $body['description'] = $desc;
    }
    if ($loc !== '') {
        $body['location'] = $loc;
    }
    $res = simko_calendar_http($userId, 'POST', simko_calendar_api_base() . '/calendars/primary/events', $body);
    if (empty($res['ok'])) {
        return $res;
    }
    $item = $res['data'];
    return [
        'ok' => true,
        'event' => [
            'id' => (string) ($item['id'] ?? ''),
            'summary' => (string) ($item['summary'] ?? $summary),
            'start' => $item['start']['dateTime'] ?? $item['start']['date'] ?? '',
            'end' => $item['end']['dateTime'] ?? $item['end']['date'] ?? '',
            'htmlLink' => (string) ($item['htmlLink'] ?? ''),
        ],
    ];
}

function simko_calendar_update(int $userId, array $args): array
{
    $id = trim((string) ($args['event_id'] ?? $args['id'] ?? ''));
    if ($id === '') {
        return ['ok' => false, 'error' => 'An event id is required to update an event.'];
    }
    $body = [];
    if (isset($args['summary']) && trim((string) $args['summary']) !== '') {
        $body['summary'] = trim((string) $args['summary']);
    }
    if (isset($args['description'])) {
        $body['description'] = (string) $args['description'];
    }
    if (isset($args['location'])) {
        $body['location'] = (string) $args['location'];
    }
    if (isset($args['start'])) {
        $body['start'] = simko_calendar_when(is_array($args['start']) ? $args['start'] : ['dateTime' => (string) $args['start']]);
    }
    if (isset($args['end'])) {
        $body['end'] = simko_calendar_when(is_array($args['end']) ? $args['end'] : ['dateTime' => (string) $args['end']]);
    }
    if ($body === []) {
        return ['ok' => false, 'error' => 'Nothing to change on that event.'];
    }
    $res = simko_calendar_http($userId, 'PATCH', simko_calendar_api_base() . '/calendars/primary/events/' . rawurlencode($id), $body);
    if (empty($res['ok'])) {
        return $res;
    }
    $item = $res['data'];
    return [
        'ok' => true,
        'event' => [
            'id' => (string) ($item['id'] ?? $id),
            'summary' => (string) ($item['summary'] ?? ''),
            'start' => $item['start']['dateTime'] ?? $item['start']['date'] ?? '',
            'end' => $item['end']['dateTime'] ?? $item['end']['date'] ?? '',
        ],
    ];
}

function simko_calendar_delete(int $userId, array $args): array
{
    $id = trim((string) ($args['event_id'] ?? $args['id'] ?? ''));
    if ($id === '') {
        return ['ok' => false, 'error' => 'An event id is required to delete an event.'];
    }
    $res = simko_calendar_http($userId, 'DELETE', simko_calendar_api_base() . '/calendars/primary/events/' . rawurlencode($id));
    if (empty($res['ok'])) {
        return $res;
    }
    return ['ok' => true, 'deleted' => true, 'event_id' => $id];
}

function simko_calendar_write_action(string $tool): string
{
    return match ($tool) {
        'calendar_create_event' => 'calendar-create',
        'calendar_update_event' => 'calendar-update',
        'calendar_delete_event' => 'calendar-delete',
        default => '',
    };
}

function simko_calendar_summary(string $tool, array $args): string
{
    $title = trim((string) ($args['summary'] ?? $args['event_id'] ?? $args['id'] ?? 'an event'));
    return match ($tool) {
        'calendar_create_event' => 'Create calendar event: ' . $title,
        'calendar_update_event' => 'Update calendar event: ' . $title,
        'calendar_delete_event' => 'Delete calendar event: ' . $title,
        default => 'Calendar change',
    };
}

function simko_calendar_run_tool(int $userId, string $tool, array $args, array $body): array
{
    $action = simko_calendar_write_action($tool);
    $approvalId = (int) ($body['approval_id'] ?? 0);
    if ($action !== '') {
        simko_guard_approval($userId, $body, $action, simko_calendar_summary($tool, $args), [
            'tool' => $tool,
            'arguments' => $args,
        ]);
        if ($approvalId > 0 && simko_calendar_already_ran($userId, $approvalId)) {
            return ['ok' => true, 'already' => true, 'note' => 'That calendar change was already made.'];
        }
    }
    $result = match ($tool) {
        'calendar_list_events' => simko_calendar_list($userId, $args),
        'calendar_create_event' => simko_calendar_create($userId, $args),
        'calendar_update_event' => simko_calendar_update($userId, $args),
        'calendar_delete_event' => simko_calendar_delete($userId, $args),
        default => ['ok' => false, 'error' => 'Unknown calendar tool.'],
    };
    if ($action !== '' && $approvalId > 0 && !empty($result['ok'])) {
        simko_audit($userId, 'calendar-ran', 'Ran approval ' . $approvalId . ': ' . simko_calendar_summary($tool, $args));
    }
    return $result;
}

function simko_calendar_already_ran(int $userId, int $approvalId): bool
{
    $stmt = simko_db()->prepare(
        'SELECT 1 FROM audit_log WHERE user_id = ? AND action = ? AND summary LIKE ? LIMIT 1'
    );
    $stmt->execute([$userId, 'calendar-ran', '%approval ' . $approvalId . '%']);
    return (bool) $stmt->fetch();
}

function simko_calendar_apply_approved(int $userId, array $body): string
{
    $approvalId = (int) ($body['approval_id'] ?? 0);
    if ($approvalId < 1) {
        return '';
    }
    $stmt = simko_db()->prepare('SELECT id, action, summary, payload, status FROM approvals WHERE id = ? AND user_id = ?');
    $stmt->execute([$approvalId, $userId]);
    $row = $stmt->fetch();
    if (!$row || (string) $row['status'] !== 'approved') {
        return '';
    }
    $payload = json_decode((string) $row['payload'], true);
    if (!is_array($payload)) {
        return '';
    }
    $tool = (string) ($payload['tool'] ?? '');
    $args = is_array($payload['arguments'] ?? null) ? $payload['arguments'] : [];
    if (simko_calendar_write_action($tool) === '' || simko_calendar_write_action($tool) !== (string) $row['action']) {
        return '';
    }
    $result = simko_calendar_run_tool($userId, $tool, $args, $body);
    return 'Calendar action result: ' . json_encode($result, JSON_UNESCAPED_UNICODE);
}

function simko_calendar_tool_schemas(): array
{
    $when = [
        'type' => 'object',
        'description' => 'A start or end time. Use date for all-day events, or dateTime as an ISO-8601 timestamp.',
        'properties' => [
            'dateTime' => ['type' => 'string', 'description' => 'ISO-8601 date and time, including offset when possible.'],
            'date' => ['type' => 'string', 'description' => 'YYYY-MM-DD for an all-day event.'],
            'timeZone' => ['type' => 'string', 'description' => 'IANA time zone, such as America/New_York.'],
        ],
    ];
    return [
        [
            'name' => 'calendar_list_events',
            'description' => 'List upcoming events on the user\'s primary Google Calendar. Use this when they ask what is on their calendar or what they have this week or today.',
            'parameters' => [
                'type' => 'object',
                'properties' => [
                    'time_min' => ['type' => 'string', 'description' => 'ISO-8601 start of the window. Defaults to the start of this week.'],
                    'time_max' => ['type' => 'string', 'description' => 'ISO-8601 end of the window. Defaults to one week after time_min.'],
                    'query' => ['type' => 'string', 'description' => 'Optional free-text search within events.'],
                    'time_zone' => ['type' => 'string', 'description' => 'IANA time zone for default windows. Defaults to America/New_York.'],
                ],
            ],
        ],
        [
            'name' => 'calendar_create_event',
            'description' => 'Create an event on the user\'s primary Google Calendar. Simko SI will ask the person to approve before this is saved.',
            'parameters' => [
                'type' => 'object',
                'properties' => [
                    'summary' => ['type' => 'string', 'description' => 'Event title.'],
                    'start' => $when,
                    'end' => $when,
                    'description' => ['type' => 'string'],
                    'location' => ['type' => 'string'],
                ],
                'required' => ['summary', 'start', 'end'],
            ],
        ],
        [
            'name' => 'calendar_update_event',
            'description' => 'Change an existing event. Simko SI will ask the person to approve before this is saved.',
            'parameters' => [
                'type' => 'object',
                'properties' => [
                    'event_id' => ['type' => 'string'],
                    'summary' => ['type' => 'string'],
                    'start' => $when,
                    'end' => $when,
                    'description' => ['type' => 'string'],
                    'location' => ['type' => 'string'],
                ],
                'required' => ['event_id'],
            ],
        ],
        [
            'name' => 'calendar_delete_event',
            'description' => 'Delete an event. Simko SI will ask the person to approve before this is removed.',
            'parameters' => [
                'type' => 'object',
                'properties' => [
                    'event_id' => ['type' => 'string'],
                ],
                'required' => ['event_id'],
            ],
        ],
    ];
}

function simko_calendar_tools_for(int $userId): array
{
    if (!simko_calendar_connected($userId)) {
        return [];
    }
    $schemas = simko_calendar_tool_schemas();
    $completions = [];
    $responses = [];
    foreach ($schemas as $schema) {
        $responses[] = [
            'type' => 'function',
            'name' => $schema['name'],
            'description' => $schema['description'],
            'parameters' => $schema['parameters'],
        ];
        $completions[] = [
            'type' => 'function',
            'function' => $schema,
        ];
    }
    return ['completions' => $completions, 'responses' => $responses];
}

function simko_calendar_system_note(): string
{
    return 'The person has connected Google Calendar. When they ask about their schedule, call calendar_list_events and answer from the tool result. '
        . 'When they ask to add, change, or cancel an event, call the matching write tool with exact times. '
        . 'Simko SI will ask them to approve each write before it is saved. After a completed calendar change is noted, tell them what changed in plain English.';
}

function simko_calendar_parse_args(mixed $raw): array
{
    if (is_array($raw)) {
        return $raw;
    }
    if (is_string($raw) && $raw !== '') {
        $decoded = json_decode($raw, true);
        return is_array($decoded) ? $decoded : [];
    }
    return [];
}

function simko_calendar_collect_calls(array $data): array
{
    $calls = [];
    $message = $data['choices'][0]['message'] ?? null;
    if (is_array($message) && !empty($message['tool_calls']) && is_array($message['tool_calls'])) {
        foreach ($message['tool_calls'] as $call) {
            if (!is_array($call)) {
                continue;
            }
            $fn = is_array($call['function'] ?? null) ? $call['function'] : [];
            $name = (string) ($fn['name'] ?? '');
            if (!str_starts_with($name, 'calendar_')) {
                continue;
            }
            $calls[] = [
                'id' => (string) ($call['id'] ?? ''),
                'name' => $name,
                'arguments' => simko_calendar_parse_args($fn['arguments'] ?? []),
                'style' => 'completions',
            ];
        }
    }
    foreach ((array) ($data['output'] ?? []) as $item) {
        if (!is_array($item)) {
            continue;
        }
        $type = (string) ($item['type'] ?? '');
        $name = (string) ($item['name'] ?? '');
        if ($type !== 'function_call' || !str_starts_with($name, 'calendar_')) {
            continue;
        }
        $calls[] = [
            'id' => (string) ($item['call_id'] ?? $item['id'] ?? ''),
            'name' => $name,
            'arguments' => simko_calendar_parse_args($item['arguments'] ?? []),
            'style' => 'responses',
            'raw' => $item,
        ];
    }
    return $calls;
}

function simko_calendar_tool_loop(int $userId, array $body, string $url, array $payload, int $timeout, string $style): array
{
    $data = simko_curl_json($url, $payload, $timeout);
    $rounds = 0;
    while ($rounds < 4) {
        $calls = simko_calendar_collect_calls($data);
        if ($calls === []) {
            break;
        }
        if ($style === 'completions') {
            $payload['messages'][] = $data['choices'][0]['message'];
        }
        foreach ($calls as $call) {
            $result = simko_calendar_run_tool($userId, $call['name'], $call['arguments'], $body);
            $out = json_encode($result, JSON_UNESCAPED_UNICODE);
            if ($style === 'completions') {
                $payload['messages'][] = [
                    'role' => 'tool',
                    'tool_call_id' => $call['id'],
                    'content' => $out,
                ];
            } else {
                $input = $payload['input'] ?? [];
                if (isset($call['raw']) && is_array($call['raw'])) {
                    $input[] = $call['raw'];
                }
                $input[] = [
                    'type' => 'function_call_output',
                    'call_id' => $call['id'],
                    'output' => $out,
                ];
                $payload['input'] = $input;
            }
        }
        $data = simko_curl_json($url, $payload, $timeout);
        $rounds++;
    }
    return $data;
}
