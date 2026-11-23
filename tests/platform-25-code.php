<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Code tab: Grok coding engine (plan -> files -> server checks -> browser sandbox tests -> fix -> zip),
// Cursor Cloud Agents as an optional engine that is a dry run unless explicitly allowed. Owner only.
$log = sys_get_temp_dir() . '/simko-code-calls-' . getmypid() . '.log';
@unlink($log);
putenv('MOCK_XAI_LOG=' . $log);
$mockPort = 8863;
$sitePort = 8864;
[$mock, $mockPipes] = platform_mock($mockPort);
@unlink($log);
$hits = static function (string $path) use ($log): int {
    return is_file($log) ? count(array_filter(explode("\n", (string) file_get_contents($log)), static fn($l) => $l === $path)) : 0;
};
$ownerEmail = 'code-owner-' . getmypid() . '@simkosi.test';
$private = platform_private('code', ['code' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$owner = platform_signup($sitePort, $ownerEmail);
$guest = platform_signup($sitePort, 'code-guest-' . getmypid() . '@simkosi.test');
$tok = $owner['token'];
$api = static fn(array $b, ?string $t = null) => platform_api($sitePort, '/api/platform', $b, $t ?? $tok);

$denied = $api(['op' => 'code-start', 'prompt' => 'calculator'], $guest['token']);
platform_assert($denied['status'] === 403, 'a non-owner cannot start a coding job');
platform_assert($hits('/v1/chat/completions') === 0, 'no xAI call for the non-owner');
platform_assert($api(['op' => 'code-jobs'], $guest['token'])['status'] === 403, 'a non-owner cannot list coding jobs');

$start = $api(['op' => 'code-start', 'prompt' => 'A calculator page. Clicking 4 + 4 = shows 8.', 'engine' => 'grok']);
$job = $start['data']['job'] ?? [];
platform_assert($start['status'] === 200 && ($job['status'] ?? '') === 'built', 'Grok builds the project and it passes the server checks');
platform_assert(count($job['plan'] ?? []) >= 3 && ($job['entry'] ?? '') === 'index.html', 'the job has a plan and an entry page');
platform_assert(count($job['files'] ?? []) === 3 && ($job['tests'][0]['name'] ?? '') === '4 + 4 = 8', 'files and an acceptance test come back');
platform_assert(($job['cost_ticks'] ?? 0) === 80000000 && ($job['cost_label'] ?? '') === '$0.0080', 'the job carries its exact xAI cost');

$v = $api(['op' => 'code-verify', 'job_id' => $job['id'], 'results' => [['name' => '4 + 4 = 8', 'passed' => true, 'detail' => 'passed']], 'errors' => []]);
platform_assert(($v['data']['job']['status'] ?? '') === 'verified' && empty($v['data']['job']['can_fix']), 'passing sandbox results mark the job verified');
$zip = $api(['op' => 'code-zip', 'job_id' => $job['id']]);
$bytes = base64_decode((string) ($zip['data']['zip_b64'] ?? ''), true);
platform_assert($zip['status'] === 200 && ($zip['data']['name'] ?? '') === 'calculator.zip' && str_starts_with((string) $bytes, "PK"), 'the project downloads as a zip');
$tmp = tempnam(sys_get_temp_dir(), 'z');
file_put_contents($tmp, $bytes);
$names = array_values(array_filter(explode("\n", (string) shell_exec('unzip -Z1 ' . escapeshellarg($tmp)))));
$test = (string) shell_exec('unzip -t ' . escapeshellarg($tmp));
$js = (string) shell_exec('unzip -p ' . escapeshellarg($tmp) . ' calculator/app.js');
@unlink($tmp);
platform_assert(str_contains($test, 'No errors detected') && str_contains($js, 'Number(a)+Number(shown)'), 'the zip passes unzip -t and holds the real code');
sort($names);
platform_assert($names === ['calculator/SIMKO-TESTS.json', 'calculator/app.js', 'calculator/index.html', 'calculator/style.css'], 'the zip holds the files and the tests');

// A failing build gets one auto-fix from the sandbox failures.
$bad = $api(['op' => 'code-start', 'prompt' => 'A calculator page BROKEN. 4 + 4 = 8.']);
$badJob = $bad['data']['job'];
platform_assert(str_contains($badJob['files'][2]['content'], 'a+shown'), 'the broken build concatenates');
$fail = $api(['op' => 'code-verify', 'job_id' => $badJob['id'], 'results' => [['name' => '4 + 4 = 8', 'passed' => false, 'detail' => 'Expected "8" in #display, saw "44"']], 'errors' => []]);
platform_assert(($fail['data']['job']['status'] ?? '') === 'tests_failed' && !empty($fail['data']['job']['can_fix']), 'failed sandbox tests can be fixed');
platform_assert(str_contains((string) ($fail['data']['job']['test_results'][0]['detail'] ?? ''), 'saw "44"'), 'the failure detail is kept');
$fix = $api(['op' => 'code-fix', 'job_id' => $badJob['id']]);
platform_assert(($fix['data']['job']['status'] ?? '') === 'built' && str_contains($fix['data']['job']['files'][2]['content'], 'Number(a)+Number(shown)'), 'Grok fixes the project from the failure');
platform_assert(($fix['data']['job']['iteration'] ?? 0) === 2 && ($fix['data']['job']['cost_ticks'] ?? 0) === 160000000, 'the fix is a second iteration and its cost adds up');
$nothing = $api(['op' => 'code-fix', 'job_id' => $job['id']]);
platform_assert($nothing['status'] === 400, 'a verified job has nothing to fix');

// Unsafe output is refused by the server checks.
$evil = $api(['op' => 'code-start', 'prompt' => 'calculator EVILPATH']);
$checks = implode(' | ', $evil['data']['job']['check_errors'] ?? []);
platform_assert(($evil['data']['job']['status'] ?? '') === 'checks_failed', 'unsafe output fails the server checks');
platform_assert(str_contains($checks, 'escape.php') && str_contains($checks, 'cdn.example.com'), 'path escapes and outside scripts are named');
platform_assert(!file_exists($private . '/escape.php') && !file_exists(dirname($private) . '/escape.php'), 'nothing is written outside the job store');

$list = $api(['op' => 'code-jobs']);
platform_assert(count($list['data']['jobs'] ?? []) === 3 && ($list['data']['engines']['cursor']['ready'] ?? null) === false, 'jobs are listed and Cursor shows as not set up');
$other = $api(['op' => 'code-job', 'job_id' => '../../config'], $tok);
platform_assert(in_array($other['status'], [400, 404], true), 'a bad job id is refused');

// Cursor engine, no key: dry run, nothing sent.
$cur = $api(['op' => 'code-start', 'prompt' => 'Add a footer', 'engine' => 'cursor', 'confirm_paid' => true]);
platform_assert(($cur['data']['job']['status'] ?? '') === 'dry_run' && ($cur['data']['job']['cursor']['launched'] ?? true) === false, 'with no Cursor key the Cursor engine is a dry run');
platform_assert(($cur['data']['job']['cursor']['request']['body']['repos'][0]['url'] ?? '') === 'https://github.com/citygangsix/simko-si', 'the dry run shows the exact request');
$chk = $api(['op' => 'cursor-check']);
platform_assert(($chk['data']['cursor']['connected'] ?? true) === false, 'the Cursor check says no key is set');
platform_assert($hits('/v1/me') === 0 && $hits('/v1/agents') === 0, 'nothing reached the Cursor API');
platform_stop($site, $sitePipes);

// Key set but launch not allowed: the key check is a free read; launches stay dry even with confirm_paid.
$private2 = platform_private('code2', ['code' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
    'cursor' => ['api_key' => 'cursor-mock-key', 'api_base' => 'http://127.0.0.1:' . $mockPort],
]);
[$site2, $site2Pipes] = platform_site($private2, 8865);
$o2 = platform_signup(8865, $ownerEmail);
$chk2 = platform_api(8865, '/api/platform', ['op' => 'cursor-check'], $o2['token']);
platform_assert(($chk2['data']['cursor']['ok'] ?? false) === true && ($chk2['data']['cursor']['account'] ?? '') === 'mock@cursor.test', 'the Cursor key is verified with GET /v1/me');
platform_assert(!str_contains(json_encode($chk2['data']), 'cursor-mock-key'), 'the Cursor key never comes back to the browser');
$dry = platform_api(8865, '/api/platform', ['op' => 'code-start', 'prompt' => 'Add a footer', 'engine' => 'cursor', 'confirm_paid' => true], $o2['token']);
platform_assert(($dry['data']['job']['status'] ?? '') === 'dry_run' && $hits('/v1/agents') === 0, 'without allow_launch nothing is launched, even with confirm_paid');
platform_assert(!str_contains(json_encode($dry['data']), 'cursor-mock-key'), 'the dry run does not show the key');
platform_stop($site2, $site2Pipes);

// allow_launch on (mock only): launch needs confirm_paid, then status refresh works.
$private3 = platform_private('code3', ['code' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
    'cursor' => ['api_key' => 'cursor-mock-key', 'api_base' => 'http://127.0.0.1:' . $mockPort, 'allow_launch' => true],
]);
[$site3, $site3Pipes] = platform_site($private3, 8866);
$o3 = platform_signup(8866, $ownerEmail);
$noConfirm = platform_api(8866, '/api/platform', ['op' => 'code-start', 'prompt' => 'Add a footer', 'engine' => 'cursor'], $o3['token']);
platform_assert(($noConfirm['data']['job']['status'] ?? '') === 'dry_run' && $hits('/v1/agents') === 0, 'a launch without confirm_paid stays a dry run');
$launch = platform_api(8866, '/api/platform', ['op' => 'code-start', 'prompt' => 'Add a footer', 'engine' => 'cursor', 'confirm_paid' => true], $o3['token']);
platform_assert(($launch['data']['job']['status'] ?? '') === 'launched' && ($launch['data']['job']['cursor']['agent_id'] ?? '') === 'bc-mock-1' && $hits('/v1/agents') === 1, 'with allow_launch and confirm_paid the (mock) agent is launched');
$refresh = platform_api(8866, '/api/platform', ['op' => 'code-job', 'job_id' => $launch['data']['job']['id']], $o3['token']);
platform_assert(($refresh['data']['job']['cursor']['status'] ?? '') === 'FINISHED', 'the Cursor job status refreshes');
platform_stop($site3, $site3Pipes);

platform_stop($mock, $mockPipes);
@unlink($log);
fwrite(STDOUT, "code tab tests passed\n");
