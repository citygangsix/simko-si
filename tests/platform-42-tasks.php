<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// P0 scheduled tasks: any prompt on a schedule, run via (mock) Responses, 5 per account, owner-only,
// spend caps skip without a call, cron runs each due task once.
$site = 9144;
$mockPort = 9145;
platform_require_free_port($site);
platform_require_free_port($mockPort);
$calls = sys_get_temp_dir() . '/simko-p0task-calls-' . getmypid() . '.log';
@unlink($calls);
putenv('MOCK_XAI_LOG=' . $calls);
platform_mock($mockPort);
$private = platform_private('p0task', ['tasks' => true, 'approvals' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [], 'user_ids' => [1]],
    'spend_caps' => ['owner_daily_usd' => 5.0, 'user_daily_usd' => 1.0, 'site_daily_usd' => 10.0, 'timezone' => 'America/New_York'],
]);
[$proc, $pipes] = platform_site($private, $site);
$a = platform_signup($site, 'taska-' . getmypid() . '@simkosi.test');
$b = platform_signup($site, 'taskb-' . getmypid() . '@simkosi.test');
$api = static fn (array $body, array $who) => platform_api($site, '/api/platform', $body, $who['token']);
$responsesCalls = static fn (): int => count(array_filter(file_exists($calls) ? (file($calls, FILE_IGNORE_NEW_LINES) ?: []) : [], fn ($l) => $l === '/v1/responses'));
$base = ['name' => 'Morning brief', 'prompt' => 'Summarize todays weather in Austin in two lines.', 'freq' => 'weekdays', 'hour' => 7, 'minute' => 30, 'tz' => 'America/Chicago'];

platform_assert(platform_api($site, '/api/platform', ['op' => 'task-list'])['status'] === 401, 'signed-out task-list is 401');
$t = $api(['op' => 'task-save'] + $base, $a);
platform_assert($t['status'] === 200 && $t['data']['task']['freq'] === 'weekdays' && $t['data']['task']['next_run_at'] > time() && $t['data']['task']['deliver_push'] === true, 'task created with its next run');
$tid = (int) $t['data']['task']['id'];
// Since the approval cards: a new task is saved paused with a task-start Yes/No card.
platform_assert($t['data']['task']['enabled'] === false && ($t['data']['approval']['action'] ?? '') === 'task-start', 'a new task waits for its Yes card');
$yes = static function (array $card, array $who, string $op, int $taskId) use ($api): array {
    platform_assert($api(['op' => 'decide', 'approval_id' => (int) $card['id'], 'decision' => 'approve'], $who)['status'] === 200, 'Yes on ' . $card['title']);
    return $api(['op' => $op, 'task_id' => $taskId, 'enabled' => true, 'approval_id' => (int) $card['id']], $who);
};
$on = $yes($t['data']['approval'], $a, 'task-toggle', $tid);
platform_assert($on['status'] === 200 && $on['data']['task']['enabled'] === true, 'after Yes the task is on');
platform_assert($api(['op' => 'task-save', 'freq' => 'hourly'] + $base, $a)['status'] === 400, 'unknown frequency is 400');
platform_assert($api(['op' => 'task-save', 'freq' => 'once', 'run_date' => '2020-01-01'] + $base, $a)['status'] === 400, 'a one-time task in the past is 400');
platform_assert($api(['op' => 'task-save', 'prompt' => str_repeat('p', 2001)] + $base, $a)['status'] === 400, 'prompt over 2000 chars is 400');
for ($i = 2; $i <= 5; $i++) {
    platform_assert($api(['op' => 'task-save', 'name' => 'Task ' . $i] + $base, $a)['status'] === 200, 'task ' . $i . ' of 5');
}
$cap = $api(['op' => 'task-save', 'name' => 'Sixth'] + $base, $a);
platform_assert($cap['status'] === 409 && ($cap['data']['cap'] ?? '') === 'tasks', 'the 6th task is refused (409, cap 5)');
platform_assert($api(['op' => 'task-save', 'id' => $tid, 'name' => 'Morning brief v2'] + $base, $a)['data']['task']['name'] === 'Morning brief v2', 'edit does not count against the cap');

// Owner-only.
platform_assert($api(['op' => 'task-list'], $b)['data']['tasks'] === [], 'another account sees no tasks');
foreach (['task-toggle', 'task-delete', 'task-runs', 'task-run-now'] as $op) {
    platform_assert($api(['op' => $op, 'task_id' => $tid, 'enabled' => false], $b)['status'] === 404, 'another account gets 404 for ' . $op);
}
platform_assert($api(['op' => 'task-save', 'id' => $tid] + $base, $b)['status'] === 404, 'another account cannot edit the task (404)');

// Run now.
$before = $responsesCalls();
$runCard = $api(['op' => 'task-run-now', 'task_id' => $tid], $a);
platform_assert($runCard['status'] === 200 && ($runCard['data']['approval']['action'] ?? '') === 'task-start' && $responsesCalls() === $before, 'run now waits for a Yes card (no call yet)');
$run = $yes($runCard['data']['approval'], $a, 'task-run-now', $tid);
platform_assert($run['status'] === 200 && $run['data']['run']['status'] === 'delivered' && str_contains($run['data']['run']['output'], 'The reef heard you') && in_array('app', $run['data']['run']['delivered'], true), 'run now calls Grok and records the result');
platform_assert($responsesCalls() === $before + 1, 'exactly one Responses call (mock)');
$runs = $api(['op' => 'task-runs', 'task_id' => $tid], $a)['data']['runs'];
platform_assert(count($runs) === 1 && $runs[0]['manual'] === true && $runs[0]['cost_usd'] > 0, 'run history with cost');
platform_assert($api(['op' => 'task-toggle', 'task_id' => $tid, 'enabled' => false], $a)['data']['task']['enabled'] === false, 'pause');
$resume = $api(['op' => 'task-toggle', 'task_id' => $tid, 'enabled' => true], $a);
platform_assert($resume['data']['task']['enabled'] === false && ($resume['data']['approval']['action'] ?? '') === 'task-start', 'resume asks first');
platform_assert($yes($resume['data']['approval'], $a, 'task-toggle', $tid)['data']['task']['enabled'] === true, 'resume after Yes');
platform_assert($api(['op' => 'task-delete', 'task_id' => 5], $a)['status'] === 200 && count($api(['op' => 'task-list'], $a)['data']['tasks']) === 4, 'delete');

// B: a confirmed non-owner task; then unconfirmed -> skipped without a call.
$bt = $api(['op' => 'task-save', 'name' => 'B daily', 'freq' => 'daily'] + $base, $b);
platform_assert($bt['status'] === 200, 'a confirmed (non-owner) account can schedule a task');
$btid = (int) $bt['data']['task']['id'];
platform_stop($proc, $pipes);

// Cron worker, in-process like routines-worker.php.
putenv('SIMKOSI_PRIVATE=' . $private);
$_SERVER['argv'] = [];
require dirname(__DIR__) . '/public_html/api/tasks.php';
$zone = new DateTimeZone('America/Chicago');
$at = static fn (string $local): int => (new DateTimeImmutable($local, $zone))->getTimestamp();
$sched = ['freq' => 'weekdays', 'hour' => 7, 'minute' => 30, 'tz' => 'America/Chicago', 'weekday' => 1, 'run_date' => ''];
platform_assert(simko_task_next_run($sched, $at('2026-11-27 08:00')) === $at('2026-11-30 07:30'), 'weekdays: Friday after 7:30 -> Monday 7:30');
platform_assert(simko_task_next_run(['freq' => 'weekly', 'weekday' => 3] + $sched, $at('2026-11-23 06:00')) === $at('2026-11-25 07:30'), 'weekly on Wednesday');
platform_assert(simko_task_next_run(['freq' => 'daily'] + $sched, $at('2026-11-23 07:29')) === $at('2026-11-23 07:30'), 'daily: later today');
platform_assert(simko_task_next_run(['freq' => 'once', 'run_date' => '2026-12-01'] + $sched, $at('2026-12-02 00:00')) === null, 'once: none after the date');

$db = simko_db();
$now = time();
$db->exec('UPDATE tasks SET next_run_at = NULL');
$db->prepare('UPDATE tasks SET next_run_at = ? WHERE id = ?')->execute([$now - 60, $tid]);
$before = $responsesCalls();
platform_assert(simko_tasks_run($now) === 1, 'cron runs the due task');
platform_assert($responsesCalls() === $before + 1, 'one Responses call for it');
$row = $db->query('SELECT * FROM tasks WHERE id = ' . $tid)->fetch();
platform_assert((int) $row['next_run_at'] > $now && $row['last_status'] === 'delivered', 'moved to its next time');
platform_assert(simko_tasks_run($now) === 0, 'not run twice');

// Missed by more than 6 hours: recorded, no call.
$db->prepare('UPDATE tasks SET next_run_at = ? WHERE id = ?')->execute([$now - 7 * 3600, $tid]);
$before = $responsesCalls();
simko_tasks_run($now);
platform_assert($responsesCalls() === $before && $db->query("SELECT status FROM task_runs WHERE task_id = $tid ORDER BY id DESC LIMIT 1")->fetchColumn() === 'missed', 'a long-missed run is skipped without a call');

// Over the daily cap: skipped_cap, no call.
$db->prepare('INSERT OR REPLACE INTO xai_spend (day, user_id, ticks) VALUES (?, ?, ?)')->execute([simko_spend_day(), (int) $row['user_id'], 6 * SIMKO_TICKS_PER_USD]);
$db->prepare('UPDATE tasks SET next_run_at = ? WHERE id = ?')->execute([$now - 60, $tid]);
$before = $responsesCalls();
simko_tasks_run($now);
platform_assert($responsesCalls() === $before && $db->query("SELECT status FROM task_runs WHERE task_id = $tid ORDER BY id DESC LIMIT 1")->fetchColumn() === 'skipped_cap', 'over the owner cap: skipped_cap, no call');

// Account that may not use Grok (unconfirmed): skipped_access, no call.
$db->prepare('UPDATE users SET confirmed = 0 WHERE id = (SELECT user_id FROM tasks WHERE id = ?)')->execute([$btid]);
$db->prepare('UPDATE tasks SET next_run_at = ?, enabled = 1 WHERE id = ?')->execute([$now - 60, $btid]);
$before = $responsesCalls();
simko_tasks_run($now);
platform_assert($responsesCalls() === $before && $db->query("SELECT status FROM task_runs WHERE task_id = $btid ORDER BY id DESC LIMIT 1")->fetchColumn() === 'skipped_access', 'unconfirmed account: skipped_access, no call');

// A one-time task turns itself off after it runs.
$db->prepare("UPDATE tasks SET freq = 'once', run_date = '2026-11-23', next_run_at = ? WHERE id = ?")->execute([$now - 60, $tid]);
$db->prepare('DELETE FROM xai_spend')->execute();
simko_tasks_run($now);
platform_assert((int) $db->query("SELECT enabled FROM tasks WHERE id = $tid")->fetchColumn() === 0, 'a one-time task is off after its run');
fwrite(STDOUT, "tasks tests passed\n");
