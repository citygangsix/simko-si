<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Daily xAI spend caps: checked before every xAI call, counted from usage.cost_in_usd_ticks.
$log = sys_get_temp_dir() . '/simko-spend-calls-' . getmypid() . '.log';
@unlink($log);
putenv('MOCK_XAI_LOG=' . $log);
[$mock, $mockPipes] = platform_mock(8876);
@unlink($log);
$calls = static function () use ($log): int {
    return is_file($log) ? count(array_filter(explode("\n", (string) file_get_contents($log)))) : 0;
};
$ownerEmail = 'spend-' . getmypid() . '@simkosi.test';
$private = platform_private('spend', ['paywall' => false, 'search' => true], [
    'xai_base_url' => 'http://127.0.0.1:8876/v1',
    'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
    'spend_caps' => ['owner_daily_usd' => 0.5, 'user_daily_usd' => 0.1, 'site_daily_usd' => 2.0],
    'deep_estimate_usd' => 0.05,
]);
[$site, $sitePipes] = platform_site($private, 8877);
$owner = platform_signup(8877, $ownerEmail);
$ok = platform_api(8877, '/api/simco/turn', ['text' => 'Say hi'], $owner['token']);
platform_assert($ok['status'] === 200, 'under the cap the owner gets a reply');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$uid = (int) $db->query('SELECT id FROM users WHERE email = ' . $db->quote($ownerEmail))->fetchColumn();
$day = (new DateTimeImmutable('now', new DateTimeZone('America/New_York')))->format('Y-m-d');
$db->prepare('INSERT INTO xai_spend (day, user_id, ticks) VALUES (?, ?, ?) ON CONFLICT(day, user_id) DO UPDATE SET ticks = excluded.ticks')
    ->execute([$day, $uid, 5000000000]);
$before = $calls();
$capped = platform_api(8877, '/api/simco/turn', ['text' => 'Say hi'], $owner['token']);
platform_assert($capped['status'] === 429, 'at the owner cap the turn is refused');
platform_assert(str_starts_with((string) ($capped['data']['error'] ?? ''), 'Daily limit reached') && str_contains((string) $capped['data']['error'], '$0.50'), 'the refusal says daily limit reached and names the limit');
platform_assert($calls() === $before, 'no xAI call is made over the cap');
$db->prepare('UPDATE xai_spend SET ticks = 0 WHERE user_id = ?')->execute([$uid]);
$db->prepare('INSERT INTO xai_spend (day, user_id, ticks) VALUES (?, 0, ?)')->execute([$day, 20000000000]);
$site2 = platform_api(8877, '/api/simco/turn', ['text' => 'Say hi'], $owner['token']);
platform_assert($site2['status'] === 429 && ($site2['data']['spend_cap'] ?? '') === 'site', 'the site-wide cap stops everyone');
$db->exec('DELETE FROM xai_spend WHERE user_id = 0');
$again = platform_api(8877, '/api/simco/turn', ['text' => 'Say hi'], $owner['token']);
platform_assert($again['status'] === 200, 'under the caps again the owner gets a reply');
// A confirmed non-owner (demo account) has the user cap, and a costly DeepSearch needs room for its estimate.
$demoEmail = 'spend-demo-' . getmypid() . '@simkosi.test';
$demo = platform_signup(8877, $demoEmail);
$db->prepare('UPDATE users SET confirmed = 1 WHERE email = ?')->execute([$demoEmail]);
$did = (int) $db->query('SELECT id FROM users WHERE email = ' . $db->quote($demoEmail))->fetchColumn();
$db->prepare('INSERT INTO xai_spend (day, user_id, ticks) VALUES (?, ?, ?) ON CONFLICT(day, user_id) DO UPDATE SET ticks = excluded.ticks')
    ->execute([$day, $did, 600000000]);
$before = $calls();
$deep = platform_api(8877, '/api/simco/turn', ['text' => 'Research reefs', 'deep_search' => true], $demo['token']);
platform_assert($deep['status'] === 429 && str_starts_with((string) ($deep['data']['error'] ?? ''), 'Daily limit reached for this kind of request'), 'DeepSearch is refused when its usual cost would pass the demo limit');
platform_assert($calls() === $before, 'no xAI call for the refused DeepSearch');
$plain = platform_api(8877, '/api/simco/turn', ['text' => 'Say hi'], $demo['token']);
platform_assert($plain['status'] === 200, 'a normal chat still works with room left');
$db->prepare('UPDATE xai_spend SET ticks = ? WHERE user_id = ? AND day = ?')->execute([1000000000, $did, $day]);
$full = platform_api(8877, '/api/simco/turn', ['text' => 'Say hi'], $demo['token']);
platform_assert($full['status'] === 429 && str_contains((string) ($full['data']['error'] ?? ''), '$0.10'), 'at the demo limit ($0.10 here) chat is refused with a friendly message');
platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
fwrite(STDOUT, "spend cap tests passed\n");
