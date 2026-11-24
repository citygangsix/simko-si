<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require __DIR__ . '/smtp.php';

$body = simko_require_post_json();
$op = (string) ($body['op'] ?? '');

switch ($op) {
    case 'signup':
        simko_signup($body);
        break;
    case 'signin':
        simko_signin($body);
        break;
    case 'signout':
        simko_signout();
        break;
    case 'me':
        simko_me();
        break;
    case 'confirm-email':
        simko_confirm($body);
        break;
    case 'request-reset':
        simko_request_reset($body);
        break;
    case 'reset-password':
        simko_reset_password($body);
        break;
    case 'export-data':
        simko_export_data();
        break;
    case 'delete-account':
        simko_delete_account($body);
        break;
    case 'twofa-verify':
        $uid = simko_twofa_verify_challenge((string) ($body['challenge'] ?? ''), (string) ($body['code'] ?? ''));
        $issued = simko_issue_token($uid);
        $who = simko_db()->prepare('SELECT email FROM users WHERE id = ?');
        $who->execute([$uid]);
        simko_ok(['token' => $issued, 'email' => (string) $who->fetchColumn()]);
        break;
    case 'twofa-status':
        simko_ok(simko_twofa_status((int) simko_require_user()['id']));
        break;
    case 'twofa-setup':
        simko_ok(simko_twofa_setup(simko_require_user()));
        break;
    case 'twofa-enable':
        simko_ok(simko_twofa_enable(simko_require_user(), (string) ($body['code'] ?? '')));
        break;
    case 'twofa-disable':
        simko_ok(simko_twofa_disable(simko_require_user(), (string) ($body['password'] ?? ''), (string) ($body['code'] ?? '')));
        break;
    case 'devices':
        simko_ok(['devices' => simko_devices((int) simko_require_user()['id'])]);
        break;
    case 'device-signout':
        simko_ok(['devices' => simko_device_signout((int) simko_require_user()['id'], (int) ($body['device_id'] ?? 0))]);
        break;
    case 'devices-signout-others':
        simko_ok(simko_devices_signout_others((int) simko_require_user()['id']));
        break;
    default:
        simko_fail(400, 'That sign-in step is not recognized.');
}

function simko_email(array $body): string
{
    $email = strtolower(trim((string) ($body['email'] ?? '')));
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        simko_fail(400, 'Enter a real email address.');
    }
    return $email;
}

function simko_password(array $body): string
{
    $password = (string) ($body['password'] ?? '');
    if (strlen($password) < 8) {
        simko_fail(400, 'Use at least 8 characters.');
    }
    if (strlen($password) > 200) {
        simko_fail(400, 'That password is too long to store.');
    }
    return $password;
}

function simko_signup(array $body): void
{
    $email = simko_email($body);
    $password = simko_password($body);
    $db = simko_db();
    $existing = $db->prepare('SELECT id FROM users WHERE email = ?');
    $existing->execute([$email]);
    if ($existing->fetch()) {
        simko_fail(400, 'That email is already registered.');
    }
    $parent = !empty($body['parent']) || !empty($body['consent']);
    if (!empty($body['parent']) && empty($body['consent'])) {
        simko_fail(400, 'A parent has to agree before a child profile can be added.');
    }
    if (simko_mail_is_smtp()) {
        simko_mail_rate_limit($email);
    }
    $confirm = bin2hex(random_bytes(16));
    $now = time();
    $insert = $db->prepare(
        'INSERT INTO users (email, password_hash, confirmed, confirm_token, created_at, role, parent_consent_at)
         VALUES (?, ?, 0, ?, ?, ?, ?)'
    );
    $insert->execute([
        $email,
        password_hash($password, PASSWORD_DEFAULT),
        $confirm,
        $now,
        $parent ? 'parent' : 'adult',
        $parent ? $now : null,
    ]);
    $id = (int) $db->lastInsertId();
    $token = simko_issue_token($id);
    simko_supabase_hook('signup', ['id' => $id, 'email' => $email]);
    if (simko_mail_is_smtp()) {
        try {
            simko_mail_confirm($email, $confirm, false);
        } catch (Throwable $e) {
            $db->prepare('DELETE FROM auth_tokens WHERE user_id = ?')->execute([$id]);
            $db->prepare('DELETE FROM users WHERE id = ?')->execute([$id]);
            simko_fail(502, 'The email could not be sent. Try again in a moment.');
        }
    }
    $out = ['token' => $token, 'email' => $email, 'parent' => $parent];
    if (simko_dev_codes_in_reply()) {
        $out['dev_token'] = $confirm;
    }
    simko_ok($out);
}

function simko_signin(array $body): void
{
    $email = simko_email($body);
    $password = (string) ($body['password'] ?? '');
    if ($password === '') {
        simko_fail(401, 'Email or password does not match.');
    }
    $limits = simko_throttle_settings();
    $ipBucket = 'ip:' . simko_client_net();
    $acctBucket = 'acct:' . $email;
    simko_throttle_check($ipBucket, $limits['ip'], $limits['window']);
    simko_throttle_check($acctBucket, $limits['account'], $limits['window']);
    $stmt = simko_db()->prepare('SELECT id, email, password_hash FROM users WHERE email = ?');
    $stmt->execute([$email]);
    $row = $stmt->fetch();
    $hash = is_array($row) ? (string) $row['password_hash'] : SIMKO_DUMMY_HASH;
    $matches = password_verify($password, $hash);
    if (!$row || !$matches) {
        simko_throttle_hit($ipBucket);
        simko_throttle_hit($acctBucket);
        simko_fail(401, 'Email or password does not match.');
    }
    simko_throttle_clear($acctBucket);
    if (simko_twofa_enabled((int) $row['id'])) {
        // Password was right; the session is only issued after the code step (op twofa-verify).
        simko_ok(['twofa_required' => true, 'challenge' => simko_twofa_challenge((int) $row['id'])]);
    }
    $token = simko_issue_token((int) $row['id']);
    simko_supabase_hook('signin', ['id' => (int) $row['id'], 'email' => $row['email']]);
    simko_ok(['token' => $token, 'email' => $row['email']]);
}

function simko_signout(): void
{
    foreach (simko_token_candidates() as $token) {
        simko_revoke_token($token);
    }
    simko_clear_cookie();
    simko_ok();
}

function simko_me(): void
{
    $user = simko_current_user();
    if (!$user) {
        if (!headers_sent()) {
            header('Content-Type: application/json; charset=utf-8');
            header('Cache-Control: no-store');
        }
        echo json_encode(['ok' => false, 'error' => 'Sign in.'], JSON_UNESCAPED_UNICODE);
        exit;
    }
    simko_ok([
        'email' => $user['email'],
        'confirmed' => (int) $user['confirmed'] === 1,
        'parent' => (int) ($user['parent_consent_at'] ?? 0) > 0,
        'consent_at' => (int) ($user['parent_consent_at'] ?? 0),
    ]);
}

function simko_confirm(array $body): void
{
    $token = trim((string) ($body['confirm_token'] ?? ''));
    if ($token === '') {
        simko_fail(400, 'Enter the confirm code first.');
    }
    $limits = simko_throttle_settings();
    $codeBucket = 'code:' . simko_client_net();
    simko_throttle_check($codeBucket, $limits['ip'], $limits['window']);
    $stmt = simko_db()->prepare(
        'UPDATE users SET confirmed = 1, confirm_token = NULL WHERE confirm_token = ?'
    );
    $stmt->execute([$token]);
    if ($stmt->rowCount() < 1) {
        simko_throttle_hit($codeBucket);
        simko_fail(400, 'Confirm failed.');
    }
    simko_ok();
}

function simko_request_reset(array $body): void
{
    $email = simko_email($body);
    $limits = simko_throttle_settings();
    $sendBucket = 'resetreq:' . simko_client_net();
    simko_throttle_check($sendBucket, $limits['reset_ip'], 3600);
    simko_throttle_hit($sendBucket);
    $db = simko_db();
    $stmt = $db->prepare('SELECT id FROM users WHERE email = ?');
    $stmt->execute([$email]);
    $row = $stmt->fetch();
    $out = [];
    if ($row) {
        if (simko_mail_is_smtp()) {
            simko_mail_rate_limit($email);
        }
        $reset = bin2hex(random_bytes(16));
        $update = $db->prepare('UPDATE users SET reset_token = ?, reset_expires = ? WHERE id = ?');
        $update->execute([$reset, time() + 3600, (int) $row['id']]);
        if (simko_mail_is_smtp()) {
            try {
                simko_mail_reset($email, $reset, false);
            } catch (Throwable $e) {
                simko_fail(502, 'The email could not be sent. Try again in a moment.');
            }
        } elseif (simko_dev_codes_in_reply()) {
            $out['dev_token'] = $reset;
        }
    }
    simko_ok($out);
}

function simko_reset_password(array $body): void
{
    $token = trim((string) ($body['reset_token'] ?? ''));
    $password = simko_password($body);
    if ($token === '') {
        simko_fail(400, 'Reset failed.');
    }
    $limits = simko_throttle_settings();
    $codeBucket = 'code:' . simko_client_net();
    simko_throttle_check($codeBucket, $limits['ip'], $limits['window']);
    $db = simko_db();
    $stmt = $db->prepare('SELECT id FROM users WHERE reset_token = ? AND reset_expires > ?');
    $stmt->execute([$token, time()]);
    $row = $stmt->fetch();
    if (!$row) {
        simko_throttle_hit($codeBucket);
        simko_fail(400, 'Reset failed.');
    }
    $update = $db->prepare(
        'UPDATE users SET password_hash = ?, reset_token = NULL, reset_expires = NULL WHERE id = ?'
    );
    $update->execute([password_hash($password, PASSWORD_DEFAULT), (int) $row['id']]);
    simko_ok();
}

/**
 * Confirm and reset codes go by email only. The one exception is a local test server:
 * mail_mode dev, config dev_codes_in_reply === true, and a loopback client. Live never qualifies.
 */
function simko_dev_codes_in_reply(): bool
{
    if (simko_mail_is_smtp()) {
        return false;
    }
    if ((simko_config_or_empty()['dev_codes_in_reply'] ?? false) !== true) {
        return false;
    }
    $ip = (string) ($_SERVER['REMOTE_ADDR'] ?? '');
    return $ip === '127.0.0.1' || $ip === '::1';
}

/**
 * In-app account deletion (Apple App Review 5.1.1(v), Google Play account deletion policy).
 * The signed-in user types DELETE to confirm. Removes the account and everything tied to it.
 * Kept on purpose: per-picture billing ledger rows (image_charges, image_billing), which are
 * financial records, with the user id only. A paid Stripe plan must be cancelled first so we never
 * delete an account that keeps getting billed.
 */
function simko_delete_account(array $body): void
{
    $user = simko_require_user();
    if (trim((string) ($body['confirm'] ?? '')) !== 'DELETE') {
        simko_fail(400, 'Type DELETE to confirm.');
    }
    $uid = (int) $user['id'];
    $db = simko_db();
    $tables = [];
    foreach ($db->query("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")->fetchAll() as $row) {
        $cols = [];
        foreach ($db->query('PRAGMA table_info(' . $row['name'] . ')')->fetchAll() as $col) {
            $cols[] = (string) $col['name'];
        }
        $tables[(string) $row['name']] = $cols;
    }
    if (isset($tables['subscriptions'])) {
        $sub = $db->prepare('SELECT status, stripe_subscription_id FROM subscriptions WHERE user_id = ?');
        $sub->execute([$uid]);
        $row = $sub->fetch();
        if (is_array($row) && in_array((string) $row['status'], ['paid', 'active', 'trialing', 'past_due'], true)
            && (string) ($row['stripe_subscription_id'] ?? '') !== '') {
            simko_fail(409, 'Cancel your $9.99/month plan first (Usage, then Manage billing). Then delete the account.', ['needs_cancel' => true]);
        }
    }
    $keep = ['users', 'image_charges', 'image_billing', 'stripe_events', 'oauth_states', 'mail_log'];
    $imageIds = [];
    if (isset($tables['generated_images'])) {
        $st = $db->prepare('SELECT id FROM generated_images WHERE user_id = ?');
        $st->execute([$uid]);
        $imageIds = array_map(static fn ($r) => (string) $r['id'], $st->fetchAll());
    }
    $db->beginTransaction();
    try {
        if (isset($tables['messages'], $tables['chats'])) {
            $db->prepare('DELETE FROM messages WHERE chat_id IN (SELECT id FROM chats WHERE user_id = ?)')->execute([$uid]);
        }
        foreach ($tables as $name => $cols) {
            if (in_array($name, $keep, true)) {
                continue;
            }
            foreach (['user_id', 'parent_user_id', 'owner_id', 'member_id'] as $col) {
                if (in_array($col, $cols, true)) {
                    $db->prepare('DELETE FROM "' . $name . '" WHERE "' . $col . '" = ?')->execute([$uid]);
                }
            }
        }
        if (isset($tables['team_invites']) && in_array('email', $tables['team_invites'], true)) {
            $db->prepare('DELETE FROM team_invites WHERE email = ?')->execute([strtolower((string) $user['email'])]);
        }
        $db->prepare('DELETE FROM users WHERE id = ?')->execute([$uid]);
        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        simko_fail(500, 'The account could not be deleted. Nothing was removed. Try again or email support.');
    }
    $dir = simko_private_dir() . '/data/images/';
    foreach ($imageIds as $id) {
        if (preg_match('/^[A-Za-z0-9_-]+$/', $id) && is_file($dir . $id . '.png')) {
            @unlink($dir . $id . '.png');
        }
    }
    @file_put_contents(simko_private_dir() . '/data/account-deletions.log', gmdate('c') . " user_id={$uid}\n", FILE_APPEND | LOCK_EX);
    simko_clear_cookie();
    simko_ok(['deleted' => true]);
}


/** Download my data: the signed-in account's own records as one JSON file. Never secrets or tokens. */
function simko_export_data(): void
{
    $user = simko_require_user();
    $uid = (int) $user['id'];
    $db = simko_db();
    $q = static function (string $sql, array $args) use ($db): array {
        try {
            $st = $db->prepare($sql);
            $st->execute($args);
            return $st->fetchAll();
        } catch (Throwable $e) {
            return [];
        }
    };
    $chats = $q('SELECT id, title, created_at, updated_at, child_profile_id FROM chats WHERE user_id = ? ORDER BY created_at', [$uid]);
    foreach ($chats as &$chat) {
        $chat['messages'] = $q('SELECT role, body, created_at FROM messages WHERE chat_id = ? ORDER BY id', [(string) $chat['id']]);
    }
    unset($chat);
    $out = [
        'exported_at' => gmdate('c'),
        'site' => 'https://simkosi.com',
        'account' => [
            'email' => (string) $user['email'],
            'created_at' => (int) ($user['created_at'] ?? 0),
            'confirmed' => (int) ($user['confirmed'] ?? 0) === 1,
        ],
        'chats' => $chats,
        'memories' => $q('SELECT fact, child_profile_id, created_at FROM memories WHERE user_id = ? ORDER BY id', [$uid]),
        'lifebook' => $q('SELECT category, label, tone, created_at FROM life_events WHERE user_id = ? ORDER BY id', [$uid]),
        'child_profiles' => $q('SELECT id, display_name, age_band, created_at FROM child_profiles WHERE parent_user_id = ? ORDER BY id', [$uid]),
        'routines' => $q('SELECT kind, hour, minute, tz, enabled, child_profile_id, created_at FROM routines WHERE user_id = ? ORDER BY id', [$uid]),
        'routine_deliveries' => $q('SELECT body, created_at FROM routine_deliveries WHERE user_id = ? ORDER BY id', [$uid]),
    ];
    simko_ok(['export' => $out]);
}
