<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_routine_kinds(): array
{
    return [
        'bedtime' => 'Bedtime story',
        'lifebook' => 'Daily Lifebook check-in',
        'homework' => 'Homework reminder',
    ];
}

function simko_routine_body(string $kind, string $name): string
{
    return match ($kind) {
        'bedtime' => $name . ', it is time for a short bedtime story. The reef is quiet and the turtle is home.',
        'lifebook' => $name . ', how was today? A sentence in Lifebook is enough.',
        'homework' => $name . ', homework time. One small piece, then a break.',
        default => $name . ', a reminder from Simko SI.',
    };
}

function simko_routine_save(int $userId, array $body): array
{
    $kind = (string) ($body['kind'] ?? '');
    $kinds = simko_routine_kinds();
    if (!isset($kinds[$kind])) {
        simko_fail(400, 'Pick a bedtime story, a Lifebook check-in, or a homework reminder.');
    }
    $hour = (int) ($body['hour'] ?? -1);
    $minute = (int) ($body['minute'] ?? -1);
    if ($hour < 0 || $hour > 23 || $minute < 0 || $minute > 59) {
        simko_fail(400, 'Pick an hour and a minute.');
    }
    $childId = simko_requested_child($userId, $body);
    $tz = simko_routine_tz((string) ($body['tz'] ?? ''));
    $now = time();
    $stmt = simko_db()->prepare(
        'INSERT INTO routines (user_id, child_profile_id, kind, hour, minute, enabled, last_run, created_at, tz)
         VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?)'
    );
    $stmt->execute([$userId, $childId, $kind, $hour, $minute, $now, $tz]);
    return ['id' => (int) simko_db()->lastInsertId(), 'kind' => $kind, 'label' => $kinds[$kind], 'hour' => $hour, 'minute' => $minute, 'tz' => $tz];
}

/** A routine's clock: the browser's time zone when valid, else config routines_timezone. */
function simko_routine_tz(string $tz): string
{
    $tz = trim($tz);
    if ($tz !== '' && in_array($tz, timezone_identifiers_list(), true)) {
        return $tz;
    }
    $fallback = (string) (simko_config_or_empty()['routines_timezone'] ?? 'America/New_York');
    return in_array($fallback, timezone_identifiers_list(), true) ? $fallback : 'America/New_York';
}

function simko_routine_rows(int $userId): array
{
    $stmt = simko_db()->prepare(
        'SELECT id, kind, hour, minute, enabled, child_profile_id FROM routines WHERE user_id = ? ORDER BY id DESC'
    );
    $stmt->execute([$userId]);
    $kinds = simko_routine_kinds();
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = [
            'id' => (int) $row['id'],
            'kind' => $row['kind'],
            'label' => $kinds[$row['kind']] ?? $row['kind'],
            'hour' => (int) $row['hour'],
            'minute' => (int) $row['minute'],
            'enabled' => (int) $row['enabled'] === 1,
            'child_id' => $row['child_profile_id'] !== null ? (int) $row['child_profile_id'] : null,
        ];
    }
    return $rows;
}

function simko_routine_deliveries(int $userId): array
{
    $stmt = simko_db()->prepare(
        'SELECT id, body, created_at FROM routine_deliveries WHERE user_id = ? ORDER BY id DESC LIMIT 20'
    );
    $stmt->execute([$userId]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = ['id' => (int) $row['id'], 'body' => $row['body'], 'created_at' => (int) $row['created_at']];
    }
    return $rows;
}

function simko_routines_run(?int $now = null): int
{
    require_once __DIR__ . '/smtp.php';
    $now = $now ?? time();
    // The worker runs every few minutes; a routine is due once its time today has
    // passed (in its own time zone) and it has not run since. Catch up for 6 hours at most.
    $catchUp = 6 * 3600;
    $stmt = simko_db()->query('SELECT r.id, r.user_id, r.child_profile_id, r.kind, r.hour, r.minute, r.last_run, r.tz, r.created_at, u.email
        FROM routines r JOIN users u ON u.id = r.user_id WHERE r.enabled = 1');
    $count = 0;
    foreach ($stmt->fetchAll() as $row) {
        $zone = new DateTimeZone(simko_routine_tz((string) ($row['tz'] ?? '')));
        $local = (new DateTimeImmutable('@' . $now))->setTimezone($zone);
        $due = $local->setTime((int) $row['hour'], (int) $row['minute'])->getTimestamp();
        if ($due > $now) {
            $due = $local->modify('-1 day')->setTime((int) $row['hour'], (int) $row['minute'])->getTimestamp();
        }
        if ($now - $due > $catchUp || (int) $row['last_run'] >= $due || (int) $row['created_at'] > $due + 3600) {
            continue;
        }
        $name = 'there';
        if ($row['child_profile_id']) {
            $child = simko_child_owned((int) $row['user_id'], (int) $row['child_profile_id']);
            if ($child) {
                $name = (string) $child['display_name'];
            }
        }
        $body = simko_routine_body((string) $row['kind'], $name);
        $insert = simko_db()->prepare(
            'INSERT INTO routine_deliveries (routine_id, user_id, body, created_at) VALUES (?, ?, ?, ?)'
        );
        $insert->execute([(int) $row['id'], (int) $row['user_id'], $body, $now]);
        $touch = simko_db()->prepare('UPDATE routines SET last_run = ? WHERE id = ?');
        $touch->execute([$now, (int) $row['id']]);
        require_once __DIR__ . '/push.php';
        simko_push_routine((int) $row['user_id'], $body);
        if (simko_mail_is_smtp()) {
            require_once __DIR__ . '/smtp.php';
            try {
                if (simko_mail_allowed((string) $row['email'])) {
                    $settings = simko_smtp_settings();
                    simko_smtp_send(
                        $settings,
                        (string) $row['email'],
                        'Simko SI reminder',
                        $body . "\r\n",
                        '<p>' . htmlspecialchars($body, ENT_QUOTES, 'UTF-8') . '</p>'
                    );
                    simko_mail_log((string) $row['email'], 'routine');
                }
            } catch (Throwable $e) {
                // The in-app note still stands if mail is down.
            }
        }
        $count++;
    }
    return $count;
}
