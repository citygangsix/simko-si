<?php
declare(strict_types=1);

/**
 * Dependency-free SMTP for sign-up confirmation and password reset.
 * mail_mode dev never opens a socket. mail_mode smtp reads the host,
 * port, user, password, and from address from simkosi-private/config.php.
 */

function simko_mail_is_smtp(): bool
{
    return (string) (simko_config_or_empty()['mail_mode'] ?? 'dev') === 'smtp';
}

function simko_smtp_settings(): array
{
    $cfg = simko_config();
    $smtp = $cfg['smtp'] ?? null;
    if (!is_array($smtp)) {
        simko_fail(500, 'Email is set to smtp, but the server has no smtp settings.');
    }
    $host = trim((string) ($smtp['host'] ?? ''));
    $port = (int) ($smtp['port'] ?? 587);
    $user = (string) ($smtp['user'] ?? '');
    $password = (string) ($smtp['password'] ?? '');
    $from = strtolower(trim((string) ($smtp['from'] ?? '')));
    $fromName = trim((string) ($smtp['from_name'] ?? 'Simko SI'));
    if ($fromName === '') {
        $fromName = 'Simko SI';
    }
    $encryption = strtolower(trim((string) ($smtp['encryption'] ?? '')));
    if ($encryption === '') {
        $encryption = $port === 465 ? 'ssl' : 'starttls';
    }
    if ($host === '' || $from === '' || !filter_var($from, FILTER_VALIDATE_EMAIL)) {
        simko_fail(500, 'Email is set to smtp, but the server has no smtp settings.');
    }
    if ($user === '' || $password === '' || str_contains($password, 'REPLACE')) {
        simko_fail(500, 'Email is set to smtp, but the mailbox password is not set.');
    }
    if (!in_array($encryption, ['starttls', 'ssl'], true) || $port < 1 || $port > 65535) {
        simko_fail(500, 'Email is set to smtp, but the port or encryption is not usable.');
    }
    $verify = array_key_exists('verify_peer', $smtp) ? !empty($smtp['verify_peer']) : true;
    $site = rtrim((string) ($cfg['site_url'] ?? 'https://simkosi.com'), '/');
    return [
        'host' => $host,
        'port' => $port,
        'user' => $user,
        'password' => $password,
        'from' => $from,
        'from_name' => $fromName,
        'encryption' => $encryption,
        'verify_peer' => $verify,
        'site_url' => $site,
    ];
}

function simko_mail_allowed(string $email): bool
{
    $stmt = simko_db()->prepare('SELECT COUNT(*) FROM mail_log WHERE email = ? AND sent_at > ?');
    $stmt->execute([strtolower($email), time() - 3600]);
    return (int) $stmt->fetchColumn() < 5;
}

function simko_mail_rate_limit(string $email): void
{
    if (!simko_mail_allowed($email)) {
        simko_fail(429, 'Too many emails to that address. Try again in an hour.');
    }
}

function simko_mail_log(string $email, string $kind): void
{
    $stmt = simko_db()->prepare('INSERT INTO mail_log (email, kind, sent_at) VALUES (?, ?, ?)');
    $stmt->execute([strtolower($email), $kind, time()]);
}

function simko_mail_confirm(string $email, string $token, bool $enforceLimit = true): void
{
    if (!simko_mail_is_smtp()) {
        return;
    }
    if ($enforceLimit) {
        simko_mail_rate_limit($email);
    }
    $settings = simko_smtp_settings();
    $link = $settings['site_url'] . '/?confirm=' . rawurlencode($token);
    $text = "Hello,\r\n\r\nConfirm your email for Simko SI. Enter this code on the site:\r\n\r\n"
        . $token . "\r\n\r\nOr open:\r\n" . $link
        . "\r\n\r\nIf you did not create this account, you can ignore this email.\r\n\r\nSimko SI\r\n";
    $html = simko_mail_html(
        'Confirm your email',
        'Enter this code on Simko SI, or use the button.',
        $token,
        $link,
        'Confirm email'
    );
    simko_smtp_send($settings, $email, 'Confirm your Simko SI email', $text, $html);
    simko_mail_log($email, 'confirm');
}

function simko_mail_reset(string $email, string $token, bool $enforceLimit = true): void
{
    if (!simko_mail_is_smtp()) {
        return;
    }
    if ($enforceLimit) {
        simko_mail_rate_limit($email);
    }
    $settings = simko_smtp_settings();
    $link = $settings['site_url'] . '/?reset=' . rawurlencode($token);
    $text = "Hello,\r\n\r\nA password reset was requested for Simko SI. Enter this code on the site:\r\n\r\n"
        . $token . "\r\n\r\nOr open:\r\n" . $link
        . "\r\n\r\nThe code expires in one hour. If you did not ask for this, you can ignore this email.\r\n\r\nSimko SI\r\n";
    $html = simko_mail_html(
        'Reset your password',
        'Enter this code on Simko SI. It expires in one hour.',
        $token,
        $link,
        'Reset password'
    );
    simko_smtp_send($settings, $email, 'Reset your Simko SI password', $text, $html);
    simko_mail_log($email, 'reset');
}

function simko_mail_html(string $heading, string $lead, string $code, string $link, string $button): string
{
    $h = htmlspecialchars($heading, ENT_QUOTES, 'UTF-8');
    $leadSafe = htmlspecialchars($lead, ENT_QUOTES, 'UTF-8');
    $codeSafe = htmlspecialchars($code, ENT_QUOTES, 'UTF-8');
    $linkSafe = htmlspecialchars($link, ENT_QUOTES, 'UTF-8');
    $buttonSafe = htmlspecialchars($button, ENT_QUOTES, 'UTF-8');
    return '<!DOCTYPE html><html><body style="margin:0;background:#03141c;color:#fff;font-family:Georgia,serif;">'
        . '<div style="max-width:32rem;margin:0 auto;padding:1.5rem;">'
        . '<p style="letter-spacing:0.04em;color:#ffd6c4;">Simko SI</p>'
        . '<h1 style="font-weight:500;font-size:1.6rem;">' . $h . '</h1>'
        . '<p style="line-height:1.45;">' . $leadSafe . '</p>'
        . '<p style="font-family:ui-monospace,monospace;font-size:1.05rem;background:#0b2430;border:1px solid rgba(255,214,196,0.45);border-radius:1rem;padding:0.8rem 1rem;">'
        . $codeSafe . '</p>'
        . '<p><a href="' . $linkSafe . '" style="display:inline-block;background:rgba(255,127,106,0.85);color:#fff;text-decoration:none;border-radius:999px;padding:0.7rem 1.1rem;">'
        . $buttonSafe . '</a></p>'
        . '<p style="color:#f3e6d8;font-size:0.92rem;">If you did not ask for this, you can ignore this email.</p>'
        . '</div></body></html>';
}

function simko_smtp_send(array $settings, string $to, string $subject, string $text, string $html): void
{
    $context = stream_context_create([
        'ssl' => [
            'verify_peer' => $settings['verify_peer'],
            'verify_peer_name' => $settings['verify_peer'],
            'allow_self_signed' => !$settings['verify_peer'],
            'peer_name' => $settings['host'],
        ],
    ]);
    $remote = ($settings['encryption'] === 'ssl' ? 'ssl://' : 'tcp://') . $settings['host'] . ':' . $settings['port'];
    $errno = 0;
    $errstr = '';
    $fp = @stream_socket_client($remote, $errno, $errstr, 20, STREAM_CLIENT_CONNECT, $context);
    if (!$fp) {
        throw new RuntimeException('smtp connect failed');
    }
    stream_set_timeout($fp, 20);
    try {
        simko_smtp_expect($fp, [220]);
        simko_smtp_cmd($fp, 'EHLO simkosi.com', [250]);
        if ($settings['encryption'] === 'starttls') {
            simko_smtp_cmd($fp, 'STARTTLS', [220]);
            $crypto = simko_smtp_crypto_method(false);
            if (!stream_socket_enable_crypto($fp, true, $crypto)) {
                throw new RuntimeException('smtp starttls failed');
            }
            simko_smtp_cmd($fp, 'EHLO simkosi.com', [250]);
        }
        simko_smtp_cmd($fp, 'AUTH LOGIN', [334]);
        simko_smtp_cmd($fp, base64_encode($settings['user']), [334]);
        simko_smtp_cmd($fp, base64_encode($settings['password']), [235]);
        simko_smtp_cmd($fp, 'MAIL FROM:<' . $settings['from'] . '>', [250]);
        simko_smtp_cmd($fp, 'RCPT TO:<' . $to . '>', [250, 251]);
        simko_smtp_cmd($fp, 'DATA', [354]);
        $payload = simko_smtp_message($settings, $to, $subject, $text, $html);
        fwrite($fp, $payload . "\r\n.\r\n");
        simko_smtp_expect($fp, [250]);
        simko_smtp_cmd($fp, 'QUIT', [221]);
    } finally {
        fclose($fp);
    }
}

function simko_smtp_crypto_method(bool $server): int
{
    if ($server) {
        $method = STREAM_CRYPTO_METHOD_TLS_SERVER;
        if (defined('STREAM_CRYPTO_METHOD_TLSv1_2_SERVER')) {
            $method = STREAM_CRYPTO_METHOD_TLSv1_2_SERVER;
            if (defined('STREAM_CRYPTO_METHOD_TLSv1_3_SERVER')) {
                $method |= STREAM_CRYPTO_METHOD_TLSv1_3_SERVER;
            }
        }
        return $method;
    }
    $method = STREAM_CRYPTO_METHOD_TLS_CLIENT;
    if (defined('STREAM_CRYPTO_METHOD_TLSv1_2_CLIENT')) {
        $method = STREAM_CRYPTO_METHOD_TLSv1_2_CLIENT;
        if (defined('STREAM_CRYPTO_METHOD_TLSv1_3_CLIENT')) {
            $method |= STREAM_CRYPTO_METHOD_TLSv1_3_CLIENT;
        }
    }
    return $method;
}

function simko_smtp_message(array $settings, string $to, string $subject, string $text, string $html): string
{
    $boundary = 'simko_' . bin2hex(random_bytes(8));
    $fromName = '=?UTF-8?B?' . base64_encode($settings['from_name']) . '?=';
    $subjectEnc = '=?UTF-8?B?' . base64_encode($subject) . '?=';
    $headers = [
        'From: ' . $fromName . ' <' . $settings['from'] . '>',
        'To: <' . $to . '>',
        'Subject: ' . $subjectEnc,
        'MIME-Version: 1.0',
        'Date: ' . gmdate('D, d M Y H:i:s') . ' +0000',
        'Message-ID: <' . bin2hex(random_bytes(8)) . '@simkosi.com>',
        'Content-Type: multipart/alternative; boundary="' . $boundary . '"',
    ];
    $body = "--" . $boundary . "\r\n"
        . "Content-Type: text/plain; charset=UTF-8\r\n"
        . "Content-Transfer-Encoding: 8bit\r\n\r\n"
        . $text . "\r\n"
        . "--" . $boundary . "\r\n"
        . "Content-Type: text/html; charset=UTF-8\r\n"
        . "Content-Transfer-Encoding: 8bit\r\n\r\n"
        . $html . "\r\n"
        . "--" . $boundary . "--";
    $raw = implode("\r\n", $headers) . "\r\n\r\n" . $body;
    $lines = preg_split("/\r\n|\n|\r/", $raw) ?: [];
    $stuffed = [];
    foreach ($lines as $line) {
        if (isset($line[0]) && $line[0] === '.') {
            $line = '.' . $line;
        }
        $stuffed[] = $line;
    }
    return implode("\r\n", $stuffed);
}

function simko_smtp_cmd($fp, string $command, array $ok): string
{
    fwrite($fp, $command . "\r\n");
    return simko_smtp_expect($fp, $ok);
}

function simko_smtp_expect($fp, array $ok): string
{
    $buffer = '';
    while (($line = fgets($fp, 515)) !== false) {
        $buffer .= $line;
        if (strlen($line) < 4 || $line[3] === ' ') {
            break;
        }
    }
    if ($buffer === '') {
        throw new RuntimeException('smtp empty reply');
    }
    $code = (int) substr($buffer, 0, 3);
    if (!in_array($code, $ok, true)) {
        throw new RuntimeException('smtp rejected the message');
    }
    return $buffer;
}
