<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';

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
    $confirm = bin2hex(random_bytes(16));
    $now = time();
    $insert = $db->prepare(
        'INSERT INTO users (email, password_hash, confirmed, confirm_token, created_at)
         VALUES (?, ?, 0, ?, ?)'
    );
    $insert->execute([$email, password_hash($password, PASSWORD_DEFAULT), $confirm, $now]);
    $id = (int) $db->lastInsertId();
    $token = simko_issue_token($id);
    simko_supabase_hook('signup', ['id' => $id, 'email' => $email]);
    $out = ['token' => $token, 'email' => $email];
    if ((simko_config_or_empty()['mail_mode'] ?? 'dev') !== 'smtp') {
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
    simko_revoke_token(simko_request_token());
    simko_clear_cookie();
    simko_ok();
}

function simko_me(): void
{
    $user = simko_current_user();
    if (!$user) {
        simko_fail(401, 'Sign in.');
    }
    simko_ok(['email' => $user['email'], 'confirmed' => (int) $user['confirmed'] === 1]);
}

function simko_confirm(array $body): void
{
    $token = trim((string) ($body['confirm_token'] ?? ''));
    if ($token === '') {
        simko_fail(400, 'Confirm failed.');
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
        $reset = bin2hex(random_bytes(16));
        $update = $db->prepare('UPDATE users SET reset_token = ?, reset_expires = ? WHERE id = ?');
        $update->execute([$reset, time() + 3600, (int) $row['id']]);
        if ((simko_config_or_empty()['mail_mode'] ?? 'dev') !== 'smtp') {
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
