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
    if (!simko_mail_is_smtp()) {
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
    $stmt = simko_db()->prepare('SELECT id, email, password_hash FROM users WHERE email = ?');
    $stmt->execute([$email]);
    $row = $stmt->fetch();
    $hash = is_array($row) ? (string) $row['password_hash'] : SIMKO_DUMMY_HASH;
    $matches = password_verify($password, $hash);
    if (!$row || !$matches) {
        simko_fail(401, 'Email or password does not match.');
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
    $stmt = simko_db()->prepare(
        'UPDATE users SET confirmed = 1, confirm_token = NULL WHERE confirm_token = ?'
    );
    $stmt->execute([$token]);
    if ($stmt->rowCount() < 1) {
        simko_fail(400, 'Confirm failed.');
    }
    simko_ok();
}

function simko_request_reset(array $body): void
{
    $email = simko_email($body);
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
        } else {
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
    $db = simko_db();
    $stmt = $db->prepare('SELECT id FROM users WHERE reset_token = ? AND reset_expires > ?');
    $stmt->execute([$token, time()]);
    $row = $stmt->fetch();
    if (!$row) {
        simko_fail(400, 'Reset failed.');
    }
    $update = $db->prepare(
        'UPDATE users SET password_hash = ?, reset_token = NULL, reset_expires = NULL WHERE id = ?'
    );
    $update->execute([password_hash($password, PASSWORD_DEFAULT), (int) $row['id']]);
    simko_ok();
}
