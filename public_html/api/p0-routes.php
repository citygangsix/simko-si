<?php
declare(strict_types=1);

/*
 * P0 ops on POST /api/platform (same CSRF/same-origin JSON check and session token as every platform op,
 * done in platform.php before this runs). Each feature has its own flag; while a flag is off its ops are 404.
 *   project-*  projects.php   library-*  library.php   task-*  tasks.php   mcp-*  mcp.php
 */

require_once __DIR__ . '/projects.php';
require_once __DIR__ . '/tasks.php';
require_once __DIR__ . '/mcp.php';

function simko_p0_route(string $op, array $user, array $body): void
{
    $userId = (int) $user['id'];
    $family = explode('-', $op, 2)[0];
    $flag = ['project' => 'projects', 'library' => 'library', 'task' => 'tasks', 'mcp' => 'mcp'][$family] ?? '';
    if ($flag === '' || !simko_flag($flag)) {
        simko_fail(404, 'That feature is turned off.');
    }
    switch ($op) {
        // ---- Saved file library ----
        case 'library-list':
            simko_ok(['files' => simko_library_list($userId, trim((string) ($body['q'] ?? '')), (string) ($body['kind'] ?? '')), 'usage' => simko_library_usage($userId)]);
        case 'library-save':
            simko_require_grok_user($user);
            simko_throttle_check('library-save:' . $userId, 60, 3600);
            simko_throttle_hit('library-save:' . $userId);
            [$row, $deduped] = simko_library_save($user, is_array($body['file'] ?? null) ? $body['file'] : $body);
            simko_ok(['file' => simko_library_public($row), 'deduped' => $deduped, 'usage' => simko_library_usage($userId)]);
        case 'library-rename':
            simko_ok(['file' => simko_library_public(simko_library_rename($userId, (string) ($body['file_id'] ?? ''), (string) ($body['name'] ?? '')))]);
        case 'library-delete':
            simko_library_delete($userId, (string) ($body['file_id'] ?? ''));
            simko_ok(['deleted' => true, 'usage' => simko_library_usage($userId)]);

        // ---- Projects ----
        case 'project-list':
            simko_ok(['projects' => simko_projects_list($userId), 'limits' => simko_projects_limits()]);
        case 'project-get':
            simko_ok(['project' => simko_project_public(simko_project_require($userId, (int) ($body['project_id'] ?? 0)), true)]);
        case 'project-save':
            simko_ok(['project' => simko_project_public(simko_project_save($userId, $body), true)]);
        case 'project-delete':
            simko_project_delete($userId, (int) ($body['project_id'] ?? 0));
            simko_ok(['deleted' => true]);
        case 'project-file-add':
            simko_ok(['project' => simko_project_public(simko_project_file_add($user, (int) ($body['project_id'] ?? 0), (string) ($body['file_id'] ?? '')), true)]);
        case 'project-file-remove':
            simko_ok(['project' => simko_project_public(simko_project_file_remove($userId, (int) ($body['project_id'] ?? 0), (string) ($body['file_id'] ?? '')), true)]);
        case 'project-chat-assign':
            simko_project_chat_assign($userId, (string) ($body['chat_id'] ?? ''), (int) ($body['project_id'] ?? 0));
            simko_ok(['assigned' => true]);

        // ---- Scheduled tasks ----
        case 'task-list':
            simko_ok(['tasks' => simko_tasks_list($userId), 'limits' => ['max_per_user' => simko_tasks_limits()['max_per_user']]]);
        case 'task-save':
            simko_require_grok_user($user);
            simko_ok(['task' => simko_task_public(simko_task_save($userId, $body))]);
        case 'task-toggle':
            simko_ok(['task' => simko_task_public(simko_task_toggle($userId, (int) ($body['task_id'] ?? 0), !empty($body['enabled'])))]);
        case 'task-delete':
            simko_task_delete($userId, (int) ($body['task_id'] ?? 0));
            simko_ok(['deleted' => true]);
        case 'task-runs':
            simko_ok(['runs' => simko_task_runs($userId, (int) ($body['task_id'] ?? 0))]);
        case 'task-run-now':
            $task = simko_task_require($userId, (int) ($body['task_id'] ?? 0));
            simko_require_grok_user($user);
            $bucket = 'task-run:' . $userId;
            simko_throttle_check($bucket, simko_tasks_limits()['run_now_per_hour'], 3600);
            simko_throttle_hit($bucket);
            @set_time_limit(150);
            simko_ok(['run' => simko_task_execute($task, true)]);

        // ---- MCP connectors ----
        case 'mcp-list':
            simko_ok(['servers' => simko_mcp_list($userId), 'allowed_hosts' => simko_mcp_allowed_hosts(), 'limits' => [
                'max_servers' => simko_mcp_settings()['max_servers'], 'max_tools' => simko_mcp_settings()['max_tools'],
            ]]);
        case 'mcp-check':
        case 'mcp-save':
        case 'mcp-refresh':
            simko_require_grok_user($user);
            simko_throttle_check('mcp:' . $userId, 30, 3600);
            simko_throttle_hit('mcp:' . $userId);
            if ($op === 'mcp-check') {
                simko_ok(['tools' => simko_mcp_probe($body)]);
            }
            if ($op === 'mcp-save') {
                simko_ok(['server' => simko_mcp_save($userId, $body)]);
            }
            simko_ok(['server' => simko_mcp_refresh($userId, (int) ($body['server_id'] ?? 0))]);
        case 'mcp-tools':
            simko_ok(['server' => simko_mcp_set_tools($userId, (int) ($body['server_id'] ?? 0), $body)]);
        case 'mcp-delete':
            simko_mcp_delete($userId, (int) ($body['server_id'] ?? 0));
            simko_ok(['deleted' => true]);
        case 'mcp-hosts':
            simko_require_grok_owner($user);
            simko_ok(['allowed_hosts' => simko_mcp_allowed_hosts(), 'config_hosts' => simko_mcp_settings()['config_hosts']]);
        case 'mcp-hosts-save':
            simko_require_grok_owner($user);
            $hosts = simko_mcp_set_allowed_hosts(is_array($body['hosts'] ?? null) ? $body['hosts'] : []);
            simko_audit($userId, 'mcp-hosts', 'Set MCP allow-list: ' . implode(', ', $hosts));
            simko_ok(['allowed_hosts' => $hosts]);
    }
    simko_fail(404, 'Unknown request.');
}
