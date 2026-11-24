<?php
declare(strict_types=1);

/*
 * Scheduled tasks (P0 #3): any prompt, run by Grok on a schedule, delivered by push and/or email.
 *   - freq: once (run_date + time), daily, weekdays (Mon-Fri), weekly (weekday 0=Sun..6=Sat); hour/minute in tz.
 *   - Cap: 5 tasks per account (config 'tasks' => ['max_per_user' => 5]); run-now 5 per hour.
 *   - Spend: each run counts toward the task owner's daily cap and the site cap. A run that would go past
 *     either cap is skipped (status skipped_cap) without calling xAI. Accounts that may not use Grok are skipped.
 *   - Runs by the routines cron (routines-worker.php calls simko_tasks_run) or tasks-worker.php.
 *   - Owner-only: rows are read with user_id; another account's task reads as 404.
 * Flag: platform.tasks (off by default).
 */

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/approvals.php';

function simko_tasks_migrate(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    $db = simko_db();
    $db->exec(
        'CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            freq TEXT NOT NULL,
            weekday INTEGER NOT NULL DEFAULT 1,
            run_date TEXT NOT NULL DEFAULT \'\',
            hour INTEGER NOT NULL,
            minute INTEGER NOT NULL,
            tz TEXT NOT NULL,
            deliver_push INTEGER NOT NULL DEFAULT 1,
            deliver_email INTEGER NOT NULL DEFAULT 0,
            use_search INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            next_run_at INTEGER,
            last_run_at INTEGER,
            last_status TEXT NOT NULL DEFAULT \'\',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(enabled, next_run_at)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS task_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            started_at INTEGER NOT NULL,
            finished_at INTEGER,
            status TEXT NOT NULL,
            manual INTEGER NOT NULL DEFAULT 0,
            cost_ticks INTEGER NOT NULL DEFAULT 0,
            output TEXT NOT NULL DEFAULT \'\',
            delivered TEXT NOT NULL DEFAULT \'\',
            error TEXT NOT NULL DEFAULT \'\'
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_task_runs_task ON task_runs(task_id, started_at)');
}

function simko_tasks_limits(): array
{
    $raw = simko_config_or_empty()['tasks'] ?? [];
    $raw = is_array($raw) ? $raw : [];
    $model = trim((string) ($raw['model'] ?? ''));
    if ($model === '') {
        $model = trim((string) (simko_config_or_empty()['model'] ?? 'grok-4.7'));
    }
    return [
        'max_per_user' => max(1, min(50, (int) ($raw['max_per_user'] ?? 5))),
        'run_now_per_hour' => max(1, min(60, (int) ($raw['run_now_per_hour'] ?? 5))),
        'max_prompt' => 2000,
        'model' => $model === '' ? 'grok-4.7' : $model,
        'estimate_usd' => max(0.0, (float) ($raw['estimate_usd'] ?? 0.02)),
        'catch_up_seconds' => 6 * 3600,
    ];
}

function simko_task_tz(string $tz): string
{
    $tz = trim($tz);
    if ($tz !== '' && in_array($tz, timezone_identifiers_list(), true)) {
        return $tz;
    }
    $fallback = (string) (simko_config_or_empty()['routines_timezone'] ?? 'America/New_York');
    return in_array($fallback, timezone_identifiers_list(), true) ? $fallback : 'America/New_York';
}

/** The first run time strictly after $after for this schedule, or null (a once task in the past). */
function simko_task_next_run(array $t, int $after): ?int
{
    $zone = new DateTimeZone(simko_task_tz((string) $t['tz']));
    $h = (int) $t['hour'];
    $m = (int) $t['minute'];
    if ($t['freq'] === 'once') {
        $d = DateTimeImmutable::createFromFormat('!Y-m-d', (string) $t['run_date'], $zone);
        if (!$d) {
            return null;
        }
        $at = $d->setTime($h, $m)->getTimestamp();
        return $at > $after ? $at : null;
    }
    $local = (new DateTimeImmutable('@' . $after))->setTimezone($zone);
    for ($i = 0; $i < 8; $i++) {
        $day = $local->modify('+' . $i . ' day')->setTime($h, $m);
        if ($day->getTimestamp() <= $after) {
            continue;
        }
        $dow = (int) $day->format('w');
        if ($t['freq'] === 'daily'
            || ($t['freq'] === 'weekdays' && $dow >= 1 && $dow <= 5)
            || ($t['freq'] === 'weekly' && $dow === (int) $t['weekday'])) {
            return $day->getTimestamp();
        }
    }
    return null;
}

function simko_task_public(array $t): array
{
    return [
        'id' => (int) $t['id'],
        'name' => (string) $t['name'],
        'prompt' => (string) $t['prompt'],
        'freq' => (string) $t['freq'],
        'weekday' => (int) $t['weekday'],
        'run_date' => (string) $t['run_date'],
        'hour' => (int) $t['hour'],
        'minute' => (int) $t['minute'],
        'tz' => (string) $t['tz'],
        'deliver_push' => (int) $t['deliver_push'] === 1,
        'deliver_email' => (int) $t['deliver_email'] === 1,
        'use_search' => (int) $t['use_search'] === 1,
        'enabled' => (int) $t['enabled'] === 1,
        'next_run_at' => $t['next_run_at'] === null ? null : (int) $t['next_run_at'],
        'last_run_at' => $t['last_run_at'] === null ? null : (int) $t['last_run_at'],
        'last_status' => (string) $t['last_status'],
    ];
}

function simko_task_owned(int $userId, int $taskId): ?array
{
    simko_tasks_migrate();
    $stmt = simko_db()->prepare('SELECT * FROM tasks WHERE id = ? AND user_id = ?');
    $stmt->execute([$taskId, $userId]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function simko_task_require(int $userId, int $taskId): array
{
    $row = $taskId > 0 ? simko_task_owned($userId, $taskId) : null;
    if (!$row) {
        simko_fail(404, 'That task was not found.');
    }
    return $row;
}

function simko_tasks_list(int $userId): array
{
    simko_tasks_migrate();
    $stmt = simko_db()->prepare('SELECT * FROM tasks WHERE user_id = ? ORDER BY id');
    $stmt->execute([$userId]);
    return array_map('simko_task_public', $stmt->fetchAll());
}

/** Checks a task form. Returns ['row' => fields, 'next' => first run] or ['error' => text]. */
function simko_task_validate(array $body, int $now): array
{
    $limits = simko_tasks_limits();
    $name = simko_clip(trim(preg_replace('/\s+/u', ' ', (string) ($body['name'] ?? '')) ?? ''), 80);
    $prompt = trim((string) ($body['prompt'] ?? ''));
    if ($name === '' || $prompt === '') {
        return ['error' => 'Give the task a name and a prompt.'];
    }
    if (simko_len($prompt) > $limits['max_prompt']) {
        return ['error' => 'A task prompt can be up to ' . $limits['max_prompt'] . ' characters.'];
    }
    $freq = (string) ($body['freq'] ?? 'daily');
    if (!in_array($freq, ['once', 'daily', 'weekdays', 'weekly'], true)) {
        return ['error' => 'Pick once, daily, weekdays, or weekly.'];
    }
    $hour = (int) ($body['hour'] ?? -1);
    $minute = (int) ($body['minute'] ?? -1);
    if ($hour < 0 || $hour > 23 || $minute < 0 || $minute > 59) {
        return ['error' => 'Pick an hour and a minute.'];
    }
    $weekday = (int) ($body['weekday'] ?? 1);
    if ($weekday < 0 || $weekday > 6) {
        return ['error' => 'Pick a day of the week.'];
    }
    $runDate = (string) ($body['run_date'] ?? '');
    if ($freq === 'once' && !preg_match('/^\d{4}-\d{2}-\d{2}$/', $runDate)) {
        return ['error' => 'Pick the date for a one-time task.'];
    }
    $row = [
        'name' => $name, 'prompt' => $prompt, 'freq' => $freq, 'weekday' => $weekday,
        'run_date' => $freq === 'once' ? $runDate : '', 'hour' => $hour, 'minute' => $minute,
        'tz' => simko_task_tz((string) ($body['tz'] ?? '')),
        'deliver_push' => array_key_exists('deliver_push', $body) ? (!empty($body['deliver_push']) ? 1 : 0) : 1,
        'deliver_email' => !empty($body['deliver_email']) ? 1 : 0,
        'use_search' => !empty($body['use_search']) ? 1 : 0,
    ];
    $next = simko_task_next_run($row, $now);
    if ($next === null) {
        return ['error' => 'That time has already passed. Pick a time in the future.'];
    }
    return ['row' => $row, 'next' => $next];
}

/** What a task-start approval covers: the exact prompt and schedule. Editing either needs a new Yes. */
function simko_task_fingerprint(array $t): string
{
    return hash('sha256', implode("\x1f", [
        (string) $t['prompt'], (string) $t['freq'], (string) (int) $t['weekday'], (string) $t['run_date'],
        (string) (int) $t['hour'], (string) (int) $t['minute'], simko_task_tz((string) $t['tz']), (string) (int) ($t['use_search'] ?? 0),
    ]));
}

/**
 * Create or edit. Since the approval cards, a task is saved paused unless it was already on and its prompt and
 * schedule did not change; turning it on goes through a task-start card (simko_task_start_card).
 */
function simko_task_save(int $userId, array $body, ?int $now = null): array
{
    simko_tasks_migrate();
    $now = $now ?? time();
    $limits = simko_tasks_limits();
    $checked = simko_task_validate($body, $now);
    if (isset($checked['error'])) {
        simko_fail(400, $checked['error']);
    }
    $row = $checked['row'];
    $next = $checked['next'];
    $db = simko_db();
    $id = (int) ($body['id'] ?? 0);
    if ($id > 0) {
        $old = simko_task_require($userId, $id);
        $keepOn = (int) $old['enabled'] === 1 && simko_task_fingerprint($old) === simko_task_fingerprint($row);
        $db->prepare('UPDATE tasks SET name = ?, prompt = ?, freq = ?, weekday = ?, run_date = ?, hour = ?, minute = ?, tz = ?,
                deliver_push = ?, deliver_email = ?, use_search = ?, next_run_at = ?, enabled = ?, updated_at = ? WHERE id = ? AND user_id = ?')
            ->execute([$row['name'], $row['prompt'], $row['freq'], $row['weekday'], $row['run_date'], $row['hour'], $row['minute'], $row['tz'],
                $row['deliver_push'], $row['deliver_email'], $row['use_search'], $next, $keepOn ? 1 : 0, $now, $id, $userId]);
        return simko_task_require($userId, $id);
    }
    $count = $db->prepare('SELECT COUNT(*) FROM tasks WHERE user_id = ?');
    $count->execute([$userId]);
    if ((int) $count->fetchColumn() >= $limits['max_per_user']) {
        simko_fail(409, 'You can have up to ' . $limits['max_per_user'] . ' scheduled tasks. Delete one to add another.', ['cap' => 'tasks']);
    }
    $db->prepare('INSERT INTO tasks (user_id, name, prompt, freq, weekday, run_date, hour, minute, tz, deliver_push, deliver_email, use_search, enabled, next_run_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)')
        ->execute([$userId, $row['name'], $row['prompt'], $row['freq'], $row['weekday'], $row['run_date'], $row['hour'], $row['minute'], $row['tz'],
            $row['deliver_push'], $row['deliver_email'], $row['use_search'], $next, $now, $now]);
    return simko_task_require($userId, (int) $db->lastInsertId());
}

/** Pausing never needs a card. Turning on is done by simko_task_apply_approval after Yes. */
function simko_task_toggle(int $userId, int $taskId, bool $enabled, ?int $now = null): array
{
    $t = simko_task_require($userId, $taskId);
    if ($enabled && (int) $t['enabled'] !== 1) {
        simko_fail(403, 'Approve starting that task first.');
    }
    $next = $enabled ? simko_task_next_run($t, $now ?? time()) : $t['next_run_at'];
    if ($enabled && $next === null) {
        simko_fail(400, 'That one-time task has already passed. Edit its date first.');
    }
    simko_db()->prepare('UPDATE tasks SET enabled = ?, next_run_at = ?, updated_at = ? WHERE id = ? AND user_id = ?')
        ->execute([$enabled ? 1 : 0, $next, time(), $taskId, $userId]);
    return simko_task_require($userId, $taskId);
}

function simko_task_schedule_label(array $t, ?int $now = null): string
{
    $tz = simko_task_tz((string) $t['tz']);
    $time = (new DateTimeImmutable('2000-01-01 ' . sprintf('%02d:%02d', (int) $t['hour'], (int) $t['minute'])))->format('g:i A');
    $days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    $when = match ((string) $t['freq']) {
        'once' => 'Once on ' . $t['run_date'],
        'weekdays' => 'Weekdays',
        'weekly' => 'Every ' . ($days[(int) $t['weekday']] ?? 'week'),
        default => 'Every day',
    };
    $label = $when . ' at ' . $time . ' (' . $tz . ')';
    $next = simko_task_next_run($t, $now ?? time());
    if ($next !== null) {
        $label .= ', next run ' . (new DateTimeImmutable('@' . $next))->setTimezone(new DateTimeZone($tz))->format('D M j, g:i A');
    }
    return $label;
}

function simko_task_runs_per_day(array $t): float
{
    return match ((string) $t['freq']) {
        'weekly' => round(1 / 7, 2),
        'weekdays' => round(5 / 7, 2),
        default => 1.0,
    };
}

/** Card facts for a task-start approval. $mode: enable | run | create. */
function simko_task_card_facts(array $t, string $mode): array
{
    $limits = simko_tasks_limits();
    $deliver = [];
    if ((int) ($t['deliver_push'] ?? 1) === 1) {
        $deliver[] = 'push';
    }
    if ((int) ($t['deliver_email'] ?? 0) === 1) {
        $deliver[] = 'email';
    }
    $deliverText = $deliver === [] ? 'in the app' : 'by ' . implode(' and ', $deliver) . ' and in the app';
    $name = (string) $t['name'];
    $prompt = simko_clip((string) $t['prompt'], 200);
    if ($mode === 'run') {
        return [
            'title' => 'Run scheduled task \'' . $name . '\' now',
            'what' => 'Grok runs "' . $prompt . '" once now and delivers the result ' . $deliverText . '.',
            'cost_usd' => $limits['estimate_usd'],
            'cost_unit' => 'for this run',
            'where' => simko_task_schedule_label($t),
        ];
    }
    $perDay = simko_task_runs_per_day($t);
    return [
        'title' => 'Start scheduled task \'' . $name . '\'',
        'what' => 'Grok runs "' . $prompt . '" on this schedule and delivers each result ' . $deliverText . '. You can pause it any time.',
        'cost_usd' => $limits['estimate_usd'],
        'cost_unit' => 'per run x ' . rtrim(rtrim(number_format($perDay, 2), '0'), '.') . ' run' . ($perDay === 1.0 ? '' : 's') . '/day',
        'where' => simko_task_schedule_label($t),
    ];
}

/**
 * Creates the task-start card for an existing task (mode enable or run). Approvals off: refuses
 * (gated actions never run ungated).
 */
function simko_task_start_card(int $userId, array $task, string $mode): array
{
    if (!simko_flag('approvals')) {
        simko_fail(403, 'Starting a task needs the in-chat Yes card, and approvals are turned off.', ['approvals_off' => true]);
    }
    $facts = simko_task_card_facts($task, $mode);
    return simko_approval_create($userId, 'task-start', $facts['title'], [
        'mode' => $mode,
        'task_id' => (int) $task['id'],
        'fingerprint' => simko_task_fingerprint($task),
    ], $facts);
}

/**
 * Runs an approved task-start once (dedupe by audit "Ran approval N:"). Re-checks the owner, the flag, that the
 * prompt and schedule are what was approved, and the caps. Returns ['ok', 'note', 'task'?, 'run'?].
 */
function simko_task_apply_approval(int $userId, array $row): array
{
    $approvalId = (int) $row['id'];
    if (!simko_flag('tasks')) {
        return ['ok' => false, 'note' => 'Scheduled tasks are turned off, so nothing was started.'];
    }
    simko_tasks_migrate();
    $p = simko_approval_payload($row);
    $mode = (string) ($p['mode'] ?? '');
    $now = time();
    if ($mode === 'create') {
        $checked = simko_task_validate(is_array($p['task'] ?? null) ? $p['task'] : [], $now);
        if (isset($checked['error'])) {
            return ['ok' => false, 'note' => 'Nothing was started: ' . $checked['error']];
        }
        $count = simko_db()->prepare('SELECT COUNT(*) FROM tasks WHERE user_id = ?');
        $count->execute([$userId]);
        if ((int) $count->fetchColumn() >= simko_tasks_limits()['max_per_user']) {
            return ['ok' => false, 'note' => 'Nothing was started: the scheduled task limit is reached. Delete one first.'];
        }
        $t = $checked['row'] + ['name' => (string) ($p['task']['name'] ?? 'Task')];
        if (!simko_approval_claim($userId, $approvalId, 'task-ran', 'Started task \'' . $t['name'] . '\'')) {
            return ['ok' => false, 'note' => 'That task was already started earlier.', 'already' => true];
        }
        simko_db()->prepare('INSERT INTO tasks (user_id, name, prompt, freq, weekday, run_date, hour, minute, tz, deliver_push, deliver_email, use_search, enabled, next_run_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)')
            ->execute([$userId, $t['name'], $t['prompt'], $t['freq'], $t['weekday'], $t['run_date'], $t['hour'], $t['minute'], $t['tz'],
                $t['deliver_push'], $t['deliver_email'], $t['use_search'], $checked['next'], $now, $now]);
        $task = simko_task_require($userId, (int) simko_db()->lastInsertId());
        $label = 'Started \'' . $task['name'] . '\', ' . simko_task_schedule_label($task);
        simko_approval_finish($userId, $approvalId, $label);
        simko_approval_note_result($label);
        return ['ok' => true, 'note' => $label, 'task' => simko_task_public($task)];
    }
    $task = simko_task_owned($userId, (int) ($p['task_id'] ?? 0));
    if (!$task) {
        return ['ok' => false, 'note' => 'That task is gone, so nothing was started.'];
    }
    if (simko_task_fingerprint($task) !== (string) ($p['fingerprint'] ?? '')) {
        return ['ok' => false, 'note' => 'The task\'s prompt or schedule changed after Yes, so nothing was started. Ask again to approve the new version.'];
    }
    if ($mode === 'enable') {
        $next = simko_task_next_run($task, $now);
        if ($next === null) {
            return ['ok' => false, 'note' => 'That one-time task has already passed, so nothing was started.'];
        }
        if (!simko_approval_claim($userId, $approvalId, 'task-ran', 'Started task \'' . $task['name'] . '\'')) {
            return ['ok' => false, 'note' => 'That task was already started earlier.', 'already' => true];
        }
        simko_db()->prepare('UPDATE tasks SET enabled = 1, next_run_at = ?, updated_at = ? WHERE id = ? AND user_id = ?')
            ->execute([$next, $now, (int) $task['id'], $userId]);
        $task = simko_task_require($userId, (int) $task['id']);
        $label = 'Started \'' . $task['name'] . '\', ' . simko_task_schedule_label($task);
        simko_approval_finish($userId, $approvalId, $label);
        simko_approval_note_result($label);
        return ['ok' => true, 'note' => $label, 'task' => simko_task_public($task)];
    }
    if ($mode === 'run') {
        if (!simko_approval_claim($userId, $approvalId, 'task-ran', 'Ran task \'' . $task['name'] . '\' once')) {
            return ['ok' => false, 'note' => 'That run already happened earlier.', 'already' => true];
        }
        @set_time_limit(150);
        $run = simko_task_execute($task, true);
        $label = 'Ran \'' . $task['name'] . '\' once: ' . $run['status'];
        simko_approval_finish($userId, $approvalId, $label);
        simko_approval_note_result($label);
        return ['ok' => $run['status'] === 'delivered', 'note' => $label . ($run['output'] !== '' ? '. Result: ' . simko_clip($run['output'], 600) : ''), 'run' => $run, 'task' => simko_task_public($task)];
    }
    return ['ok' => false, 'note' => 'Unknown task approval.'];
}

/** chat.php: on the turn after Yes, runs an approved task-start once. Returns a note for the system prompt. */
function simko_tasks_apply_approved(int $userId, array $body): string
{
    $row = simko_approval_for_apply($userId, $body, ['task-start']);
    if (!$row) {
        return '';
    }
    $res = simko_task_apply_approval($userId, $row);
    return 'Scheduled task result: ' . $res['note'] . ' Tell the person what happened in one or two lines. Do not ask to start it again.';
}

function simko_task_delete(int $userId, int $taskId): void
{
    simko_task_require($userId, $taskId);
    $db = simko_db();
    $db->prepare('DELETE FROM task_runs WHERE task_id = ? AND user_id = ?')->execute([$taskId, $userId]);
    $db->prepare('DELETE FROM tasks WHERE id = ? AND user_id = ?')->execute([$taskId, $userId]);
}

function simko_task_runs(int $userId, int $taskId): array
{
    simko_task_require($userId, $taskId);
    $stmt = simko_db()->prepare('SELECT * FROM task_runs WHERE task_id = ? AND user_id = ? ORDER BY id DESC LIMIT 30');
    $stmt->execute([$taskId, $userId]);
    return array_map(static fn ($r) => [
        'id' => (int) $r['id'], 'started_at' => (int) $r['started_at'], 'finished_at' => $r['finished_at'] === null ? null : (int) $r['finished_at'],
        'status' => (string) $r['status'], 'manual' => (int) $r['manual'] === 1, 'cost_usd' => round((int) $r['cost_ticks'] / SIMKO_TICKS_PER_USD, 4),
        'output' => (string) $r['output'], 'delivered' => $r['delivered'] === '' ? [] : explode(',', (string) $r['delivered']), 'error' => (string) $r['error'],
    ], $stmt->fetchAll());
}

/** Whether a run fits under the task owner's and the site's daily caps (without stopping the request). */
function simko_task_spend_ok(array $user, float $estimateUsd): bool
{
    $caps = simko_spend_caps();
    $est = (int) round($estimateUsd * SIMKO_TICKS_PER_USD);
    if (simko_spend_site_today() + $est >= (int) round($caps['site'] * SIMKO_TICKS_PER_USD)) {
        return false;
    }
    $cap = simko_is_grok_owner($user) ? $caps['owner'] : $caps['user'];
    return simko_spend_today((int) $user['id']) + $est < (int) round($cap * SIMKO_TICKS_PER_USD);
}

/** Text of a Responses reply. */
function simko_task_reply_text(array $data): string
{
    if (is_string($data['output_text'] ?? null) && trim($data['output_text']) !== '') {
        return trim($data['output_text']);
    }
    $parts = [];
    foreach ((array) ($data['output'] ?? []) as $item) {
        if (is_array($item) && ($item['type'] ?? '') === 'message') {
            foreach ((array) ($item['content'] ?? []) as $c) {
                if (is_array($c) && is_string($c['text'] ?? null)) {
                    $parts[] = $c['text'];
                }
            }
        }
    }
    return trim(implode("\n", $parts));
}

/**
 * Runs one task for its owner: checks access and caps, calls Grok (Responses), records task_runs,
 * delivers. Never stops the request or the cron loop. Returns the task_runs row as public data.
 */
function simko_task_execute(array $task, bool $manual, ?int $now = null): array
{
    simko_tasks_migrate();
    $now = $now ?? time();
    $db = simko_db();
    $stmt = $db->prepare('SELECT * FROM users WHERE id = ?');
    $stmt->execute([(int) $task['user_id']]);
    $user = $stmt->fetch() ?: null;
    $limits = simko_tasks_limits();
    $status = 'delivered';
    $output = '';
    $error = '';
    $ticks = 0;
    $delivered = [];
    $previousSpendUser = $GLOBALS['simko_spend_user'] ?? null;
    if (!$user || !simko_can_use_grok($user)) {
        $status = 'skipped_access';
        $error = 'This account may not use Grok.';
    } elseif (!simko_task_spend_ok($user, $limits['estimate_usd'])) {
        $status = 'skipped_cap';
        $error = 'Daily Grok limit reached; skipped without a call.';
    } else {
        $key = trim((string) (simko_config_or_empty()['xai_api_key'] ?? ''));
        if ($key === '' || str_contains($key, 'REPLACE')) {
            $status = 'failed';
            $error = 'The Grok key is not set on the server yet.';
        } else {
            $local = (new DateTimeImmutable('@' . $now))->setTimezone(new DateTimeZone(simko_task_tz((string) $task['tz'])));
            $payload = [
                'model' => $limits['model'],
                'input' => [
                    ['role' => 'system', 'content' => 'You are Simko SI running a scheduled task the person set up ("' . $task['name'] . '"). '
                        . 'It is ' . $local->format('l, F j, Y g:i A T') . '. Write the result they will read in a notification or email: clear, brief, no preamble.'],
                    ['role' => 'user', 'content' => (string) $task['prompt']],
                ],
                'store' => false,
            ];
            if ((int) $task['use_search'] === 1) {
                require_once __DIR__ . '/search.php';
                $payload['tools'] = simko_search_tools(false);
                $payload['include'] = ['no_inline_citations'];
            }
            $GLOBALS['simko_spend_user'] = ['id' => (int) $user['id'], 'email' => (string) $user['email']];
            $url = simko_xai_url_plain('responses');
            $res = simko_curl($url, (string) json_encode($payload, JSON_UNESCAPED_UNICODE), [
                'Content-Type: application/json', 'Authorization: Bearer ' . $key, 'Accept: application/json',
            ], 120);
            $data = json_decode($res['body'], true);
            if (!is_array($data) || $res['code'] >= 400 || $res['code'] === 0) {
                simko_log_upstream($res['code'], $res['error']);
                $status = 'failed';
                $error = 'Grok could not be reached.';
            } else {
                $ticks = (int) ($data['usage']['cost_in_usd_ticks'] ?? 0);
                simko_spend_add($ticks);
                $output = simko_clip(simko_task_reply_text($data), 8000);
                if ($output === '') {
                    $status = 'failed';
                    $error = 'No reply came back.';
                }
            }
        }
    }
    if ($status === 'delivered') {
        $delivered[] = 'app';
        if ((int) $task['deliver_push'] === 1) {
            require_once __DIR__ . '/push.php';
            try {
                [$sent] = simko_push_send_user((int) $task['user_id'], [
                    'title' => 'Simko SI: ' . $task['name'],
                    'body' => simko_clip($output, 180),
                    'tag' => 'simko-task-' . (int) $task['id'],
                    'url' => '/?task=' . (int) $task['id'],
                ]);
                if ($sent > 0) {
                    $delivered[] = 'push';
                }
            } catch (Throwable $e) {
                // The in-app result still stands.
            }
        }
        if ((int) $task['deliver_email'] === 1 && $user) {
            require_once __DIR__ . '/smtp.php';
            try {
                if (simko_mail_is_smtp() && simko_mail_allowed((string) $user['email'])) {
                    simko_smtp_send(simko_smtp_settings(), (string) $user['email'], 'Simko SI: ' . $task['name'],
                        $output . "\r\n", '<p>' . nl2br(htmlspecialchars($output, ENT_QUOTES, 'UTF-8')) . '</p>');
                    simko_mail_log((string) $user['email'], 'task');
                    $delivered[] = 'email';
                }
            } catch (Throwable $e) {
                // Mail down: the in-app result still stands.
            }
        }
    }
    $GLOBALS['simko_spend_user'] = $previousSpendUser;
    if ($previousSpendUser === null) {
        unset($GLOBALS['simko_spend_user']);
    }
    $db->prepare('INSERT INTO task_runs (task_id, user_id, started_at, finished_at, status, manual, cost_ticks, output, delivered, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)')
        ->execute([(int) $task['id'], (int) $task['user_id'], $now, time(), $status, $manual ? 1 : 0, $ticks, $output, implode(',', $delivered), $error]);
    $runId = (int) $db->lastInsertId();
    $db->prepare('UPDATE tasks SET last_run_at = ?, last_status = ? WHERE id = ?')->execute([$now, $status, (int) $task['id']]);
    return ['id' => $runId, 'status' => $status, 'output' => $output, 'delivered' => $delivered, 'error' => $error, 'cost_usd' => round($ticks / SIMKO_TICKS_PER_USD, 4)];
}

/** Cron: runs every due task once, moves it to its next time. Missed runs older than 6 hours are skipped. */
function simko_tasks_run(?int $now = null): int
{
    if (!simko_flag('tasks')) {
        return 0;
    }
    simko_tasks_migrate();
    $now = $now ?? time();
    $limits = simko_tasks_limits();
    $db = simko_db();
    $stmt = $db->prepare('SELECT * FROM tasks WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ? ORDER BY next_run_at LIMIT 200');
    $stmt->execute([$now]);
    $ran = 0;
    foreach ($stmt->fetchAll() as $task) {
        $due = (int) $task['next_run_at'];
        // Claim the run first so two overlapping workers cannot both run it.
        $next = simko_task_next_run($task, max($now, $due));
        $claim = $db->prepare('UPDATE tasks SET next_run_at = ?, enabled = ? WHERE id = ? AND next_run_at = ?');
        $claim->execute([$next, $next === null ? 0 : 1, (int) $task['id'], $due]);
        if ($claim->rowCount() !== 1) {
            continue;
        }
        if ($now - $due > $limits['catch_up_seconds']) {
            $db->prepare('INSERT INTO task_runs (task_id, user_id, started_at, finished_at, status, error) VALUES (?, ?, ?, ?, ?, ?)')
                ->execute([(int) $task['id'], (int) $task['user_id'], $now, $now, 'missed', 'The server was not running at that time.']);
            continue;
        }
        simko_task_execute($task, false, $now);
        $ran++;
    }
    return $ran;
}
