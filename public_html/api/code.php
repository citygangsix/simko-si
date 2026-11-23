<?php
declare(strict_types=1);

/*
 * Code tab: auto-coding for the owner.
 *
 * Primary engine "grok" (billed to the site's xAI key, owner only):
 *   1. spec + plan + files + acceptance tests in ONE structured-output call
 *      (POST /v1/chat/completions with response_format json_schema,
 *       https://docs.x.ai/developers/model-capabilities/text/structured-outputs);
 *   2. server-side sandbox checks on the generated project (safe paths, sizes, entry page,
 *      local references only, no outside scripts);
 *   3. the browser runs the project in a sandboxed iframe (scripts only, no site cookies or
 *      storage) with a small test harness that clicks through the acceptance tests and reports back;
 *   4. on a failure, one "fix" call sends the failures back to Grok for a corrected project.
 *   The project downloads as a zip. Every call's real cost (usage.cost_in_usd_ticks) is kept on the job.
 *
 * Optional engine "cursor" (Cursor Cloud Agents API, POST https://api.cursor.com/v1/agents,
 * https://cursor.com/docs/cloud-agent/api/endpoints). Paid Cursor time, so it only builds a
 * dry-run request unless config cursor.allow_launch is true AND the request says confirm_paid.
 */

require_once __DIR__ . '/bootstrap.php';

const SIMKO_CODE_MAX_FILES = 12;
const SIMKO_CODE_MAX_FILE_BYTES = 120000;
const SIMKO_CODE_MAX_TOTAL_BYTES = 400000;
const SIMKO_CODE_MAX_ITERATIONS = 3;

function simko_code_model(): string
{
    $cfg = simko_config_or_empty();
    $model = trim((string) ($cfg['code_model'] ?? ''));
    if ($model === '') {
        $model = trim((string) ($cfg['model'] ?? 'grok-4.7'));
    }
    return $model !== '' ? $model : 'grok-4.7';
}

function simko_code_dir(int $userId): string
{
    $dir = simko_private_dir() . '/data/code/' . $userId;
    if (!is_dir($dir) && !@mkdir($dir, 0750, true) && !is_dir($dir)) {
        simko_fail(500, 'Simko SI cannot store coding jobs.');
    }
    return $dir;
}

function simko_code_job_path(int $userId, string $jobId): string
{
    if (!preg_match('/^[a-f0-9]{16}$/', $jobId)) {
        simko_fail(404, 'That coding job is not on this account.');
    }
    return simko_code_dir($userId) . '/' . $jobId . '.json';
}

function simko_code_load(int $userId, string $jobId): array
{
    $path = simko_code_job_path($userId, $jobId);
    $job = is_file($path) ? json_decode((string) file_get_contents($path), true) : null;
    if (!is_array($job) || (int) ($job['user_id'] ?? 0) !== $userId) {
        simko_fail(404, 'That coding job is not on this account.');
    }
    return $job;
}

function simko_code_save(array $job): void
{
    $job['updated_at'] = time();
    $path = simko_code_job_path((int) $job['user_id'], (string) $job['id']);
    $tmp = $path . '.tmp';
    file_put_contents($tmp, json_encode($job, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE));
    rename($tmp, $path);
}

function simko_code_list(int $userId): array
{
    $rows = [];
    foreach (glob(simko_code_dir($userId) . '/*.json') ?: [] as $file) {
        $job = json_decode((string) file_get_contents($file), true);
        if (is_array($job)) {
            $rows[] = simko_code_public($job, false);
        }
    }
    usort($rows, static fn ($a, $b) => $b['created_at'] <=> $a['created_at']);
    return array_slice($rows, 0, 20);
}

/** What the browser sees. Files only when asked; never any key. */
function simko_code_public(array $job, bool $withFiles = true): array
{
    $out = [
        'id' => $job['id'],
        'engine' => $job['engine'],
        'prompt' => $job['prompt'],
        'title' => $job['title'] ?? '',
        'summary' => $job['summary'] ?? '',
        'plan' => $job['plan'] ?? [],
        'entry' => $job['entry'] ?? '',
        'status' => $job['status'],
        'checks' => $job['checks'] ?? [],
        'verify' => $job['verify'] ?? null,
        'iteration' => count($job['iterations'] ?? []),
        'cost_ticks' => (int) ($job['cost_ticks'] ?? 0),
        'cost_label' => '$' . number_format(((int) ($job['cost_ticks'] ?? 0)) / 1e10, 4),
        'created_at' => (int) $job['created_at'],
        'error' => $job['error'] ?? '',
    ];
    $labels = [
        'planning' => 'Grok is planning and writing the files', 'built' => 'built, waiting for the sandbox tests',
        'checks_failed' => 'server checks failed', 'verified' => 'all tests passed in the sandbox',
        'tests_failed' => 'some tests failed', 'fixing' => 'Grok is fixing the failures', 'failed' => 'failed',
        'dry_run' => 'dry run, nothing launched', 'launched' => 'launched on Cursor',
    ];
    $out['status_label'] = $labels[$job['status']] ?? (string) $job['status'];
    $out['check_errors'] = [];
    foreach ($job['checks'] ?? [] as $c) {
        if (empty($c['ok'])) {
            $out['check_errors'][] = $c['name'] . ': ' . $c['detail'];
        }
    }
    $out['test_results'] = [];
    foreach ($job['verify']['results'] ?? [] as $r) {
        $out['test_results'][] = ['name' => $r['name'], 'passed' => (bool) $r['passed'], 'detail' => $r['error'] ?: 'passed'];
    }
    foreach ($job['verify']['errors'] ?? [] as $e) {
        $out['test_results'][] = ['name' => 'page error', 'passed' => false, 'detail' => $e];
    }
    $out['can_fix'] = ($job['engine'] ?? '') === 'grok'
        && in_array($job['status'], ['checks_failed', 'tests_failed'], true)
        && count($job['iterations'] ?? []) < SIMKO_CODE_MAX_ITERATIONS;
    if ($withFiles) {
        $out['files'] = array_map(static fn(array $f): array => $f + ['bytes' => strlen((string) $f['content'])], $job['files'] ?? []);
        $out['tests'] = $job['tests'] ?? [];
        if (isset($job['cursor'])) {
            $out['cursor'] = $job['cursor'];
        }
    }
    return $out;
}

function simko_code_schema(): array
{
    $str = ['type' => 'string'];
    return [
        'type' => 'object',
        'additionalProperties' => false,
        'required' => ['title', 'summary', 'plan', 'entry', 'files', 'tests'],
        'properties' => [
            'title' => $str,
            'summary' => $str,
            'plan' => ['type' => 'array', 'items' => $str],
            'entry' => $str,
            'files' => ['type' => 'array', 'items' => [
                'type' => 'object',
                'additionalProperties' => false,
                'required' => ['path', 'content'],
                'properties' => ['path' => $str, 'content' => $str],
            ]],
            'tests' => ['type' => 'array', 'items' => [
                'type' => 'object',
                'additionalProperties' => false,
                'required' => ['name', 'steps'],
                'properties' => [
                    'name' => $str,
                    'steps' => ['type' => 'array', 'items' => [
                        'type' => 'object',
                        'additionalProperties' => false,
                        'required' => ['action', 'selector', 'value'],
                        'properties' => [
                            'action' => ['type' => 'string', 'enum' => ['click', 'type', 'expect_text', 'wait']],
                            'selector' => $str,
                            'value' => $str,
                        ],
                    ]],
                ],
            ]],
        ],
    ];
}

function simko_code_system(): string
{
    return 'You are the Simko SI coding agent. Build exactly what the person asks for as a small, self-contained '
        . 'static web project: HTML, CSS and plain JavaScript only. Rules: no frameworks, no CDNs, no network '
        . 'requests, no external scripts, styles or fonts; reference files only by relative path; at most '
        . SIMKO_CODE_MAX_FILES . ' files; the entry file is an .html page. Give every element a test needs a '
        . 'stable id. First write a short plan (3 to 6 steps). Then write the complete files. Then write '
        . 'acceptance tests that prove the request works, as steps a person would do: click (selector), '
        . 'type (selector, value), expect_text (selector, value: text the element must contain), wait '
        . '(value: milliseconds). Use CSS id selectors like #btn4. Keep value an empty string when unused.';
}

/** One structured-output call to Grok. Returns [project array, cost ticks]. */
function simko_code_grok_call(array $messages): array
{
    $before = simko_xai_cost_total();
    $data = simko_curl_json(simko_xai_url('chat/completions'), [
        'model' => simko_code_model(),
        'messages' => $messages,
        'response_format' => [
            'type' => 'json_schema',
            'json_schema' => ['name' => 'simko_code_project', 'strict' => true, 'schema' => simko_code_schema()],
        ],
    ], 170);
    $ticks = simko_xai_cost_total() - $before;
    $raw = simko_choice_text($data);
    $project = json_decode($raw, true);
    if (!is_array($project)) {
        // Some replies wrap the JSON in a code fence.
        if (preg_match('/\{.*\}/s', $raw, $m)) {
            $project = json_decode($m[0], true);
        }
    }
    if (!is_array($project)) {
        simko_fail(502, 'Grok did not return a project. Nothing was saved.', ['cost_ticks' => $ticks]);
    }
    return [$project, $ticks];
}

/** Server-side sandbox checks on a generated project. Cleans paths; returns [files, checks, ok]. */
function simko_code_check(array $project): array
{
    $checks = [];
    $files = [];
    $total = 0;
    $okAll = true;
    $add = static function (string $name, bool $ok, string $detail = '') use (&$checks, &$okAll): void {
        $checks[] = ['name' => $name, 'ok' => $ok, 'detail' => $detail];
        if (!$ok) {
            $okAll = false;
        }
    };
    $allowedExt = ['html', 'htm', 'css', 'js', 'json', 'svg', 'txt', 'md'];
    foreach ((array) ($project['files'] ?? []) as $file) {
        if (!is_array($file)) {
            continue;
        }
        $path = ltrim(str_replace('\\', '/', trim((string) ($file['path'] ?? ''))), './');
        $content = (string) ($file['content'] ?? '');
        $ext = strtolower(pathinfo($path, PATHINFO_EXTENSION));
        if ($path === '' || str_contains($path, '..') || !preg_match('#^[A-Za-z0-9_\-][A-Za-z0-9_\-./]*$#', $path) || !in_array($ext, $allowedExt, true)) {
            $add('safe file path', false, 'Refused file "' . simko_clip($path, 80) . '"');
            continue;
        }
        if (strlen($content) > SIMKO_CODE_MAX_FILE_BYTES) {
            $add('file size', false, $path . ' is over ' . SIMKO_CODE_MAX_FILE_BYTES . ' bytes');
            continue;
        }
        $total += strlen($content);
        $files[$path] = $content;
    }
    $add('file count', count($files) >= 1 && count($files) <= SIMKO_CODE_MAX_FILES, count($files) . ' files');
    $add('total size', $total <= SIMKO_CODE_MAX_TOTAL_BYTES, $total . ' bytes');
    $entry = ltrim((string) ($project['entry'] ?? ''), './');
    if ($entry === '' || !isset($files[$entry])) {
        foreach (array_keys($files) as $p) {
            if (preg_match('/\.html?$/', $p)) {
                $entry = $p;
                break;
            }
        }
    }
    $add('entry page', $entry !== '' && isset($files[$entry]) && preg_match('/\.html?$/', $entry) === 1, $entry);
    $outside = [];
    $missing = [];
    foreach ($files as $path => $content) {
        if (!preg_match('/\.(html?|css)$/', $path)) {
            continue;
        }
        preg_match_all('#(?:src|href)\s*=\s*["\']([^"\'\#]+)["\']#i', $content, $refs);
        preg_match_all('#@import\s+(?:url\()?["\']?([^"\')\s;]+)#i', $content, $imports);
        foreach (array_merge($refs[1], $imports[1]) as $ref) {
            $ref = trim($ref);
            if (preg_match('#^(https?:)?//#i', $ref)) {
                // Plain links to other sites are fine; loading code from them is not.
                if (preg_match('#<(script|link|img|iframe)[^>]+["\']' . preg_quote($ref, '#') . '#i', $content) || str_ends_with($path, '.css')) {
                    $outside[] = $ref;
                }
                continue;
            }
            if (preg_match('#^(data:|mailto:|tel:|javascript:)#i', $ref) || $ref === '') {
                continue;
            }
            $local = ltrim(preg_replace('#[?].*$#', '', $ref) ?? $ref, './');
            if (!isset($files[$local])) {
                $missing[] = $ref;
            }
        }
    }
    $add('no outside scripts or styles', $outside === [], implode(', ', array_slice($outside, 0, 3)));
    $add('local files exist', $missing === [], implode(', ', array_slice(array_unique($missing), 0, 5)));
    $tests = [];
    foreach ((array) ($project['tests'] ?? []) as $test) {
        if (!is_array($test)) {
            continue;
        }
        $steps = [];
        foreach ((array) ($test['steps'] ?? []) as $step) {
            if (!is_array($step)) {
                continue;
            }
            $action = (string) ($step['action'] ?? '');
            if (!in_array($action, ['click', 'type', 'expect_text', 'wait'], true)) {
                continue;
            }
            $steps[] = [
                'action' => $action,
                'selector' => simko_clip((string) ($step['selector'] ?? ''), 200),
                'value' => simko_clip((string) ($step['value'] ?? ''), 500),
            ];
        }
        if ($steps !== []) {
            $tests[] = ['name' => simko_clip((string) ($test['name'] ?? 'test'), 120), 'steps' => array_slice($steps, 0, 40)];
        }
    }
    $add('acceptance tests', $tests !== [], count($tests) . ' tests');
    $list = [];
    foreach ($files as $path => $content) {
        $list[] = ['path' => $path, 'content' => $content];
    }
    return [$list, array_slice($tests, 0, 10), $entry, $checks, $okAll];
}

function simko_code_apply(array &$job, array $project, int $ticks, string $kind): void
{
    [$files, $tests, $entry, $checks, $ok] = simko_code_check($project);
    $job['title'] = simko_clip((string) ($project['title'] ?? $job['title'] ?? 'Project'), 120);
    $job['summary'] = simko_clip((string) ($project['summary'] ?? ''), 600);
    $plan = [];
    foreach ((array) ($project['plan'] ?? []) as $step) {
        if (is_string($step) && trim($step) !== '') {
            $plan[] = simko_clip(trim($step), 300);
        }
    }
    $job['plan'] = array_slice($plan, 0, 10);
    $job['files'] = $files;
    $job['tests'] = $tests;
    $job['entry'] = $entry;
    $job['checks'] = $checks;
    $job['verify'] = null;
    $job['status'] = $ok ? 'built' : 'checks_failed';
    $job['cost_ticks'] = (int) ($job['cost_ticks'] ?? 0) + $ticks;
    $job['iterations'][] = ['kind' => $kind, 'cost_ticks' => $ticks, 'checks_ok' => $ok, 'at' => time()];
}

function simko_code_start(array $user, string $prompt, string $engine, array $options = []): array
{
    $prompt = trim($prompt);
    if ($prompt === '' || simko_len($prompt) > 4000) {
        simko_fail(400, 'Describe the coding job in under 4000 characters.');
    }
    $job = [
        'id' => bin2hex(random_bytes(8)),
        'user_id' => (int) $user['id'],
        'engine' => $engine,
        'prompt' => $prompt,
        'status' => 'planning',
        'iterations' => [],
        'cost_ticks' => 0,
        'created_at' => time(),
    ];
    if ($engine === 'cursor') {
        $job['title'] = simko_clip($prompt, 80);
        $job['cursor'] = simko_cursor_launch($prompt, $options);
        $job['status'] = $job['cursor']['launched'] ? 'launched' : 'dry_run';
        simko_code_save($job);
        return $job;
    }
    // Grok builds can take a minute or two: save the job as "planning" and build after the reply is sent.
    simko_code_save($job);
    return $job;
}

/** Runs after the HTTP reply is sent. If anything stops the build, the job is marked failed, never left hanging. */
function simko_code_background(array $job, string $kind): void
{
    $GLOBALS['simko_code_bg'] = ['user_id' => (int) $job['user_id'], 'id' => (string) $job['id']];
    register_shutdown_function(static function (): void {
        $bg = $GLOBALS['simko_code_bg'] ?? null;
        if (!is_array($bg)) {
            return;
        }
        $path = simko_code_job_path($bg['user_id'], $bg['id']);
        $cur = is_file($path) ? json_decode((string) file_get_contents($path), true) : null;
        if (is_array($cur) && in_array($cur['status'] ?? '', ['planning', 'fixing'], true)) {
            $cur['status'] = $cur['files'] ?? [] ? 'tests_failed' : 'failed';
            $cur['error'] = 'Grok did not return a usable project. Try again or reword the request.';
            $cur['cost_ticks'] = (int) ($cur['cost_ticks'] ?? 0) + (int) ($GLOBALS['simko_xai_cost_ticks'] ?? 0);
            simko_code_save($cur);
        }
    });
    if ($kind === 'build') {
        [$project, $ticks] = simko_code_grok_call([
            ['role' => 'system', 'content' => simko_code_system()],
            ['role' => 'user', 'content' => (string) $job['prompt']],
        ]);
        simko_code_apply($job, $project, $ticks, 'build');
        simko_code_save($job);
    } else {
        simko_code_fix_run($job);
    }
    $GLOBALS['simko_code_bg'] = null;
}

/** Sends the JSON reply and closes the connection so long work can continue server-side. */
function simko_code_reply_then_continue(array $payload): void
{
    ignore_user_abort(true);
    @set_time_limit(240);
    $body = json_encode(['ok' => true] + $payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    if (session_status() === PHP_SESSION_ACTIVE) {
        session_write_close();
    }
    while (ob_get_level() > 0) {
        ob_end_clean();
    }
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    header('Connection: close');
    header('Content-Length: ' . strlen((string) $body));
    echo $body;
    flush();
    if (function_exists('litespeed_finish_request')) {
        litespeed_finish_request();
    } elseif (function_exists('fastcgi_finish_request')) {
        fastcgi_finish_request();
    }
    // The reply is sent: anything printed later (an error from the build) must not reach the client.
    ob_start(static fn(string $chunk): string => '');
}

/** Results from the browser test harness: [{name, passed, error}], plus page errors. */
function simko_code_record_verify(array $job, mixed $results, mixed $errors): array
{
    $rows = [];
    $passed = 0;
    foreach (is_array($results) ? array_slice($results, 0, 20) : [] as $r) {
        if (!is_array($r)) {
            continue;
        }
        $ok = !empty($r['passed']);
        $passed += $ok ? 1 : 0;
        $rows[] = ['name' => simko_clip((string) ($r['name'] ?? ''), 120), 'passed' => $ok, 'error' => simko_clip((string) ($r['error'] ?? $r['detail'] ?? ''), 300)];
    }
    $errs = [];
    foreach (is_array($errors) ? array_slice($errors, 0, 10) : [] as $e) {
        $errs[] = simko_clip((string) $e, 300);
    }
    $all = $rows !== [] && $passed === count($rows) && $errs === [];
    $job['verify'] = ['passed' => $passed, 'total' => count($rows), 'all_passed' => $all, 'results' => $rows, 'errors' => $errs, 'at' => time()];
    $job['status'] = $all ? 'verified' : 'tests_failed';
    simko_code_save($job);
    return $job;
}

function simko_code_fix(array $job): array
{
    if (($job['engine'] ?? '') !== 'grok') {
        simko_fail(400, 'Only Grok jobs can be fixed here.');
    }
    if (count($job['iterations'] ?? []) >= SIMKO_CODE_MAX_ITERATIONS) {
        simko_fail(429, 'This job has had ' . SIMKO_CODE_MAX_ITERATIONS . ' tries. Start a new job or change the request.');
    }
    $problems = [];
    foreach ($job['checks'] ?? [] as $c) {
        if (empty($c['ok'])) {
            $problems[] = 'Server check failed: ' . $c['name'] . ' (' . $c['detail'] . ')';
        }
    }
    foreach ($job['verify']['results'] ?? [] as $r) {
        if (empty($r['passed'])) {
            $problems[] = 'Test failed: ' . $r['name'] . ': ' . $r['error'];
        }
    }
    foreach ($job['verify']['errors'] ?? [] as $e) {
        $problems[] = 'Page error: ' . $e;
    }
    if ($problems === []) {
        simko_fail(400, 'Nothing failed, so there is nothing to fix.');
    }
    $job['fix_problems'] = array_slice($problems, 0, 12);
    $job['status'] = 'fixing';
    simko_code_save($job);
    return $job;
}

function simko_code_fix_run(array $job): array
{
    $problems = (array) ($job['fix_problems'] ?? []);
    $current = json_encode(['entry' => $job['entry'], 'files' => $job['files'], 'tests' => $job['tests']], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    [$project, $ticks] = simko_code_grok_call([
        ['role' => 'system', 'content' => simko_code_system()],
        ['role' => 'user', 'content' => $job['prompt']],
        ['role' => 'assistant', 'content' => $current],
        ['role' => 'user', 'content' => "The project above was run in a browser sandbox and failed:\n- " . implode("\n- ", array_slice($problems, 0, 12))
            . "\nFix the project. Return the complete corrected project (all files) and keep tests that check the original request."],
    ]);
    simko_code_apply($job, $project, $ticks, 'fix');
    simko_code_save($job);
    return $job;
}

function simko_code_zip(array $job): string
{
    $base = preg_replace('/[^a-z0-9\-]+/', '-', strtolower((string) ($job['title'] ?? 'project'))) ?: 'project';
    $base = trim(substr($base, 0, 40), '-') ?: 'project';
    $entries = [];
    foreach ($job['files'] ?? [] as $file) {
        $entries[$base . '/' . $file['path']] = (string) $file['content'];
    }
    $entries[$base . '/SIMKO-TESTS.json'] = (string) json_encode($job['tests'] ?? [], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    return simko_zip_bytes($entries);
}

/** Minimal zip writer (deflate when zlib is present), so downloads do not depend on ZipArchive. */
function simko_zip_bytes(array $entries): string
{
    $out = '';
    $central = '';
    $count = 0;
    $dosTime = 0;
    $dosDate = (2026 - 1980) << 9 | 1 << 5 | 1;
    foreach ($entries as $name => $data) {
        $name = (string) $name;
        $crc = crc32($data);
        $method = 0;
        $stored = $data;
        if (function_exists('gzdeflate')) {
            $deflated = gzdeflate($data, 6);
            if (is_string($deflated) && strlen($deflated) < strlen($data)) {
                $method = 8;
                $stored = $deflated;
            }
        }
        $offset = strlen($out);
        $out .= pack('VvvvvvVVVvv', 0x04034b50, 20, 0x0800, $method, $dosTime, $dosDate, $crc, strlen($stored), strlen($data), strlen($name), 0) . $name . $stored;
        $central .= pack('VvvvvvvVVVvvvvvVV', 0x02014b50, 20, 20, 0x0800, $method, $dosTime, $dosDate, $crc, strlen($stored), strlen($data), strlen($name), 0, 0, 0, 0, 0, $offset) . $name;
        $count++;
    }
    return $out . $central . pack('VvvvvVVv', 0x06054b50, 0, 0, $count, $count, strlen($central), strlen($out), 0);
}

/* ---------- Cursor Cloud Agents (optional engine) ---------- */

function simko_cursor_settings(): array
{
    $cfg = simko_config_or_empty()['cursor'] ?? [];
    $cfg = is_array($cfg) ? $cfg : [];
    $env = getenv('CURSOR_API_KEY');
    $key = is_string($env) && trim($env) !== '' ? trim($env) : trim((string) ($cfg['api_key'] ?? ''));
    return [
        'api_key' => $key,
        'api_base' => rtrim((string) ($cfg['api_base'] ?? 'https://api.cursor.com'), '/'),
        'repository' => trim((string) ($cfg['repository'] ?? 'https://github.com/citygangsix/simko-si')),
        'ref' => trim((string) ($cfg['ref'] ?? 'main')),
        'model' => trim((string) ($cfg['model'] ?? '')),
        'allow_launch' => ($cfg['allow_launch'] ?? false) === true,
        'connected' => $key !== '',
    ];
}

function simko_cursor_http(string $method, string $path, ?array $body = null): array
{
    $s = simko_cursor_settings();
    if (!$s['connected']) {
        return ['code' => 0, 'data' => null, 'error' => 'No Cursor API key is set.'];
    }
    $ch = curl_init($s['api_base'] . $path);
    $opts = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 30,
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $s['api_key'], 'Accept: application/json', 'Content-Type: application/json'],
    ];
    if ($body !== null) {
        $opts[CURLOPT_POSTFIELDS] = json_encode($body, JSON_UNESCAPED_SLASHES);
    }
    curl_setopt_array($ch, $opts);
    $raw = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    $data = is_string($raw) ? json_decode($raw, true) : null;
    return ['code' => $code, 'data' => is_array($data) ? $data : null, 'error' => $err];
}

/** Free read: GET /v1/me. Says whether the key works; never returns the key. */
function simko_cursor_check(): array
{
    $s = simko_cursor_settings();
    if (!$s['connected']) {
        return ['connected' => false, 'ok' => false, 'message' => 'No Cursor API key is set on the server.'];
    }
    $r = simko_cursor_http('GET', '/v1/me');
    $ok = $r['code'] === 200;
    $who = is_array($r['data']) ? (string) ($r['data']['userEmail'] ?? $r['data']['email'] ?? $r['data']['apiKeyName'] ?? '') : '';
    return ['connected' => true, 'ok' => $ok, 'status' => $r['code'], 'account' => $who, 'allow_launch' => $s['allow_launch']];
}

function simko_cursor_request_body(string $prompt): array
{
    $s = simko_cursor_settings();
    $body = [
        'prompt' => ['text' => $prompt],
        'name' => simko_clip('Simko SI: ' . $prompt, 100),
        'repos' => [['url' => $s['repository'], 'startingRef' => $s['ref']]],
    ];
    if ($s['model'] !== '') {
        $body['model'] = $s['model'];
    }
    return $body;
}

/** Dry run by default. A real (paid) run needs allow_launch in config AND confirm_paid from the owner. */
function simko_cursor_launch(string $prompt, array $options): array
{
    $s = simko_cursor_settings();
    $body = simko_cursor_request_body($prompt);
    $out = [
        'launched' => false,
        'request' => ['method' => 'POST', 'url' => $s['api_base'] . '/v1/agents', 'body' => $body],
        'key_set' => $s['connected'],
    ];
    $confirm = !empty($options['confirm_paid']);
    if (!$s['connected']) {
        $out['reason'] = 'No Cursor API key is set, so this is a dry run. Nothing was sent to Cursor.';
        return $out;
    }
    if (!$s['allow_launch'] || !$confirm || !empty($options['dry_run'])) {
        $out['reason'] = 'Dry run: Cursor agent runs use paid Cursor time and need Joseph\'s OK (config cursor.allow_launch plus a confirmed run). Nothing was sent to Cursor.';
        return $out;
    }
    $r = simko_cursor_http('POST', '/v1/agents', $body);
    if ($r['code'] < 200 || $r['code'] >= 300) {
        $out['reason'] = 'Cursor refused the run (HTTP ' . $r['code'] . ').';
        return $out;
    }
    $out['launched'] = true;
    $out['agent_id'] = (string) ($r['data']['agent']['id'] ?? $r['data']['id'] ?? '');
    $out['run_id'] = (string) ($r['data']['run']['id'] ?? '');
    $out['status'] = (string) ($r['data']['run']['status'] ?? $r['data']['status'] ?? 'queued');
    return $out;
}

function simko_cursor_refresh(array $job): array
{
    $agentId = (string) ($job['cursor']['agent_id'] ?? '');
    if (empty($job['cursor']['launched']) || $agentId === '') {
        return $job;
    }
    $r = simko_cursor_http('GET', '/v1/agents/' . rawurlencode($agentId));
    if ($r['code'] === 200 && is_array($r['data'])) {
        $job['cursor']['status'] = (string) ($r['data']['status'] ?? $r['data']['agent']['status'] ?? $job['cursor']['status'] ?? '');
        $job['cursor']['summary'] = simko_clip((string) ($r['data']['summary'] ?? ''), 2000);
        simko_code_save($job);
    }
    return $job;
}
