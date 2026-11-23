<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// The cron worker delivers a routine once its local time has passed, even when the
// worker wakes up in a later hour, and never twice the same day.
$private = platform_private('routinesrun', ['routines' => true, 'paywall' => false]);
[$site, $pipes] = platform_site($private, 8875);
$user = platform_signup(8875, 'rt-' . getmypid() . '@simkosi.test');
$saved = platform_api(8875, '/api/platform', ['op' => 'save-routine', 'kind' => 'lifebook', 'hour' => 21, 'minute' => 50, 'tz' => 'America/Chicago'], $user['token']);
platform_assert($saved['status'] === 200 && ($saved['data']['routine']['tz'] ?? $saved['data']['tz'] ?? 'America/Chicago') === 'America/Chicago', 'routine saved with the browser time zone');
platform_stop($site, $pipes);
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
platform_assert($db->query('SELECT tz FROM routines')->fetchColumn() === 'America/Chicago', 'time zone stored on the routine');
$db->exec('UPDATE routines SET created_at = 0');
putenv('SIMKOSI_PRIVATE=' . $private);
$_SERVER['argv'] = [];
require dirname(__DIR__) . '/public_html/api/routines.php';
$zone = new DateTimeZone('America/Chicago');
$at = static fn (string $local): int => (new DateTimeImmutable($local, $zone))->getTimestamp();
platform_assert(simko_routines_run($at('2026-11-23 21:45')) === 0, 'not yet due at 21:45 Chicago');
platform_assert(simko_routines_run($at('2026-11-23 22:00')) === 1, 'delivered at 22:00 although the hour changed');
platform_assert(simko_routines_run($at('2026-11-23 22:15')) === 0, 'not delivered twice');
platform_assert(simko_routines_run($at('2026-11-24 21:55')) === 1, 'delivered again the next day');
platform_assert(simko_routines_run($at('2026-11-26 09:00')) === 0, 'a missed day is not caught up hours later');
$n = (int) $db->query('SELECT COUNT(*) FROM routine_deliveries')->fetchColumn();
platform_assert($n === 2, 'two deliveries recorded');
fwrite(STDOUT, "routines run tests passed\n");
