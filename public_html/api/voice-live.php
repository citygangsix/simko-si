<?php
declare(strict_types=1);

/**
 * Live (realtime) voice: mint a short-lived xAI client secret so the browser
 * can talk to wss://api.x.ai/v1/realtime without ever seeing the site key.
 * Per-user and site-wide daily minute caps live in config 'live_voice'.
 */

function simko_live_voice_config(): array
{
    $raw = simko_config_or_empty()['live_voice'] ?? [];
    $raw = is_array($raw) ? $raw : [];
    $user = (int) ($raw['user_daily_minutes'] ?? 10);
    $site = (int) ($raw['site_daily_minutes'] ?? 60);
    $ttl = (int) ($raw['token_ttl_seconds'] ?? 300);
    $model = trim((string) ($raw['model'] ?? 'grok-voice-latest'));
    if ($model === '') {
        $model = 'grok-voice-latest';
    }
    return [
        'user_daily_minutes' => max(0, $user),
        'site_daily_minutes' => max(0, $site),
        'token_ttl_seconds' => max(30, min(3600, $ttl > 0 ? $ttl : 300)),
        'model' => $model,
        'usd_per_minute' => 0.08,
    ];
}

function simko_live_voice_map(): array
{
    $map = [];
    foreach (simko_voice_catalog() as $voice) {
        $map[$voice['id']] = $voice['xai'];
    }
    return $map;
}

function simko_live_voice_used(int $userId): int
{
    $stmt = simko_db()->prepare('SELECT seconds FROM live_voice_usage WHERE day = ? AND user_id = ?');
    $stmt->execute([simko_spend_day(), $userId]);
    return (int) ($stmt->fetchColumn() ?: 0);
}

function simko_live_voice_site_used(): int
{
    $stmt = simko_db()->prepare('SELECT COALESCE(SUM(seconds), 0) FROM live_voice_usage WHERE day = ?');
    $stmt->execute([simko_spend_day()]);
    return (int) $stmt->fetchColumn();
}

function simko_live_voice_status(?array $user): array
{
    $cfg = simko_live_voice_config();
    $userSec = $cfg['user_daily_minutes'] * 60;
    $siteSec = $cfg['site_daily_minutes'] * 60;
    $used = $user ? simko_live_voice_used((int) $user['id']) : 0;
    $siteUsed = simko_live_voice_site_used();
    return [
        'day' => simko_spend_day(),
        'timezone' => simko_spend_caps()['timezone'],
        'user_cap_seconds' => $userSec,
        'site_cap_seconds' => $siteSec,
        'user_used_seconds' => $used,
        'site_used_seconds' => $siteUsed,
        'remaining_user_seconds' => max(0, $userSec - $used),
        'remaining_site_seconds' => max(0, $siteSec - $siteUsed),
        'usd_per_minute' => $cfg['usd_per_minute'],
    ];
}

function simko_live_voice_public_status(?array $user): array
{
    $status = simko_live_voice_status($user);
    return [
        'day' => $status['day'],
        'timezone' => $status['timezone'],
        'user_cap_seconds' => $status['user_cap_seconds'],
        'site_cap_seconds' => $status['site_cap_seconds'],
        'user_used_seconds' => $status['user_used_seconds'],
        'site_used_seconds' => $status['site_used_seconds'],
        'remaining_user_seconds' => $status['remaining_user_seconds'],
        'remaining_site_seconds' => $status['remaining_site_seconds'],
    ];
}

function simko_live_voice_check(array $user): array
{
    $status = simko_live_voice_status($user);
    $cfg = simko_live_voice_config();
    if ($status['remaining_site_seconds'] <= 0) {
        simko_fail(429, 'Daily limit reached: Simko SI has used its ' . $cfg['site_daily_minutes'] . ' minutes of live voice for today. It resets at midnight Eastern time.', array_merge(simko_live_voice_public_status($user), ['live_voice_cap' => 'site']));
    }
    if ($status['remaining_user_seconds'] <= 0) {
        simko_fail(429, 'Daily limit reached: you have used today\'s ' . $cfg['user_daily_minutes'] . ' minutes of live voice. It resets at midnight Eastern time.', array_merge(simko_live_voice_public_status($user), ['live_voice_cap' => 'user']));
    }
    return $status;
}

function simko_live_voice_is_mock(): bool
{
    $host = (string) parse_url(rtrim((string) (simko_config()['xai_base_url'] ?? 'https://api.x.ai/v1'), '/'), PHP_URL_HOST);
    return $host !== 'api.x.ai';
}

function simko_live_voice_log_line(array $user, int $added, array $status): void
{
    $dir = simko_private_dir() . '/data';
    if (!is_dir($dir)) {
        return;
    }
    $tz = simko_spend_caps()['timezone'];
    try {
        $at = (new DateTimeImmutable('now', new DateTimeZone($tz)))->format('c');
    } catch (Throwable $e) {
        $at = date('c');
    }
    $line = $at
        . ' user_id=' . (int) $user['id']
        . ' added_seconds=' . $added
        . ' user_total=' . $status['user_used_seconds']
        . ' site_total=' . $status['site_used_seconds']
        . ' remaining_user=' . $status['remaining_user_seconds']
        . ' remaining_site=' . $status['remaining_site_seconds']
        . PHP_EOL;
    @file_put_contents($dir . '/live-voice.log', $line, FILE_APPEND);
}

function simko_live_voice_add(array $user, int $seconds, ?string $sessionId = null): array
{
    $seconds = max(0, $seconds);
    $status = simko_live_voice_status($user);
    $room = min($status['remaining_user_seconds'], $status['remaining_site_seconds']);
    $add = min($seconds, $room);
    $capped = $seconds > $add;
    if ($add > 0) {
        $db = simko_db();
        $day = simko_spend_day();
        $uid = (int) $user['id'];
        $now = time();
        $stmt = $db->prepare(
            'INSERT INTO live_voice_usage (day, user_id, seconds, updated_at) VALUES (?, ?, ?, ?)
             ON CONFLICT(day, user_id) DO UPDATE SET seconds = seconds + excluded.seconds, updated_at = excluded.updated_at'
        );
        $stmt->execute([$day, $uid, $add, $now]);
        $log = $db->prepare('INSERT INTO live_voice_log (day, user_id, seconds, session_id, at) VALUES (?, ?, ?, ?, ?)');
        $log->execute([$day, $uid, $add, $sessionId, $now]);
        $ticks = (int) round($add * simko_live_voice_config()['usd_per_minute'] / 60 * SIMKO_TICKS_PER_USD);
        if ($ticks > 0) {
            $GLOBALS['simko_spend_user'] = $user;
            simko_spend_add($ticks);
            simko_xai_cost_note(simko_xai_url_plain('realtime'), ['usage' => ['cost_in_usd_ticks' => $ticks]]);
        }
    }
    $status = simko_live_voice_status($user);
    if ($add > 0) {
        simko_live_voice_log_line($user, $add, $status);
    }
    $status['added_seconds'] = $add;
    $status['capped'] = $capped || $status['remaining_user_seconds'] <= 0 || $status['remaining_site_seconds'] <= 0;
    return $status;
}

function simko_live_voice_quota(): void
{
    $body = simko_require_post_json();
    unset($body);
    $user = simko_require_user();
    simko_require_grok_user($user);
    simko_ok(simko_live_voice_public_status($user));
}

function simko_live_voice_session(): void
{
    $body = simko_require_post_json();
    $user = simko_require_user();
    simko_require_grok_user($user);
    $status = simko_live_voice_check($user);
    $voice = simko_voice_by_id(strtolower(trim((string) ($body['voice'] ?? 'coral')))) ?: simko_voice_by_id('coral');
    if (!$voice) {
        simko_fail(400, 'Choose a voice from the voice picker.');
    }
    $cfg = simko_live_voice_config();
    $ttl = $cfg['token_ttl_seconds'];
    $result = simko_curl(simko_xai_url('realtime/client_secrets'), json_encode([
        'expires_after' => ['seconds' => $ttl],
    ], JSON_UNESCAPED_SLASHES), [
        'Content-Type: application/json',
        'Authorization: Bearer ' . simko_api_key(),
        'Accept: application/json',
    ], 20);
    $decoded = json_decode($result['body'], true);
    $value = is_array($decoded) ? trim((string) ($decoded['value'] ?? '')) : '';
    if ($result['code'] >= 400 || $value === '') {
        simko_log_upstream($result['code'], $result['error'] !== '' ? $result['error'] : 'realtime client_secrets failed');
        $hint = '';
        if (is_array($decoded)) {
            $err = $decoded['error'] ?? $decoded['message'] ?? null;
            if (is_array($err)) {
                $hint = trim((string) ($err['message'] ?? $err['code'] ?? ''));
            } elseif (is_string($err)) {
                $hint = $err;
            }
            $hint = preg_replace('/xai-[A-Za-z0-9._-]{8,}/', 'xai-…', $hint) ?? $hint;
            $hint = preg_replace('/Bearer\s+\S+/i', 'Bearer …', $hint) ?? $hint;
        }
        $msg = 'Live voice is not available just now.';
        if ($hint !== '') {
            $msg .= ' ' . $hint;
        }
        simko_fail(502, $msg);
    }
    $sessionId = bin2hex(random_bytes(16));
    $now = time();
    $expires = is_array($decoded) && isset($decoded['expires_at']) ? (int) $decoded['expires_at'] : ($now + $ttl);
    $stmt = simko_db()->prepare(
        'INSERT INTO live_voice_sessions (id, user_id, started_at, expires_at, reported_seconds) VALUES (?, ?, ?, ?, 0)'
    );
    $stmt->execute([$sessionId, (int) $user['id'], $now, $expires]);
    $instructions = (string) (simko_config()['system_prompt'] ?? 'You are Simko SI. Reply in clear everyday English.');
    $instructions .= ' You are speaking out loud, so keep answers conversational and concise.';
    simko_ok(array_merge(simko_live_voice_public_status($user), [
        'value' => $value,
        'expires_at' => $expires,
        'session_id' => $sessionId,
        'model' => $cfg['model'],
        'ws_url' => 'wss://api.x.ai/v1/realtime?model=' . rawurlencode($cfg['model']),
        'voice' => $voice['id'],
        'xai_voice' => $voice['xai'],
        'voice_map' => simko_live_voice_map(),
        'instructions' => $instructions,
        'mock' => simko_live_voice_is_mock(),
    ]));
}

function simko_live_voice_usage(): void
{
    $body = simko_require_post_json();
    $user = simko_require_user();
    simko_require_grok_user($user);
    $sessionId = preg_replace('/[^a-f0-9]/', '', strtolower((string) ($body['session_id'] ?? ''))) ?? '';
    if (strlen($sessionId) !== 32) {
        simko_fail(400, 'That live-voice session is missing.');
    }
    $stmt = simko_db()->prepare('SELECT id, user_id, started_at, expires_at, reported_seconds FROM live_voice_sessions WHERE id = ?');
    $stmt->execute([$sessionId]);
    $session = $stmt->fetch();
    if (!$session || (int) $session['user_id'] !== (int) $user['id']) {
        simko_fail(404, 'That live-voice session was not found.');
    }
    $requested = max(0, (int) ($body['seconds'] ?? 0));
    if ($requested > 900) {
        $requested = 900;
    }
    $now = time();
    $elapsed = max(0, $now - (int) $session['started_at']);
    $grace = 5;
    $already = (int) $session['reported_seconds'];
    $roomElapsed = max(0, $elapsed + $grace - $already);
    $add = min($requested, $roomElapsed);
    // Late reports a little after expiry are fine; not long after.
    if ($now > ((int) $session['expires_at'] + 120)) {
        $add = 0;
    }
    $status = simko_live_voice_add($user, $add, $sessionId);
    if ($status['added_seconds'] > 0) {
        $upd = simko_db()->prepare('UPDATE live_voice_sessions SET reported_seconds = reported_seconds + ? WHERE id = ?');
        $upd->execute([$status['added_seconds'], $sessionId]);
    }
    simko_ok(array_merge(simko_live_voice_public_status($user), [
        'added_seconds' => $status['added_seconds'],
        'capped' => $status['capped'] && ($status['remaining_user_seconds'] <= 0 || $status['remaining_site_seconds'] <= 0),
        'session_id' => $sessionId,
    ]));
}
