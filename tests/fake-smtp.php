<?php
declare(strict_types=1);

/**
 * Local SMTP stand-in for tests. One process, many connections.
 * argv: port starttls|ssl cert key capture user password
 */
$port = (int) ($argv[1] ?? 1587);
$mode = (string) ($argv[2] ?? 'starttls');
$cert = (string) ($argv[3] ?? '');
$key = (string) ($argv[4] ?? '');
$capture = (string) ($argv[5] ?? '');
$user = (string) ($argv[6] ?? 'mailer@simkosi.test');
$pass = (string) ($argv[7] ?? 'test-secret');

$context = stream_context_create([
    'ssl' => [
        'local_cert' => $cert,
        'local_pk' => $key,
        'verify_peer' => false,
        'verify_peer_name' => false,
        'allow_self_signed' => true,
        'security_level' => 0,
    ],
]);
$scheme = $mode === 'ssl' ? 'ssl' : 'tcp';
$errno = 0;
$errstr = '';
$server = stream_socket_server(
    $scheme . '://127.0.0.1:' . $port,
    $errno,
    $errstr,
    STREAM_SERVER_BIND | STREAM_SERVER_LISTEN,
    $context
);
if (!$server) {
    fwrite(STDERR, $errstr . PHP_EOL);
    exit(1);
}
file_put_contents($capture . '.ready', (string) $port);

function smtp_read($fp): string
{
    $line = fgets($fp, 4096);
    return $line === false ? '' : rtrim($line, "\r\n");
}

function smtp_write($fp, string $line): void
{
    fwrite($fp, $line . "\r\n");
}

function smtp_crypto_server(): int
{
    $method = STREAM_CRYPTO_METHOD_TLS_SERVER;
    if (defined('STREAM_CRYPTO_METHOD_TLSv1_2_SERVER')) {
        $method = STREAM_CRYPTO_METHOD_TLSv1_2_SERVER;
        if (defined('STREAM_CRYPTO_METHOD_TLSv1_3_SERVER')) {
            $method |= STREAM_CRYPTO_METHOD_TLSv1_3_SERVER;
        }
    }
    return $method;
}

while (true) {
    $conn = @stream_socket_accept($server, 2);
    if (!$conn) {
        continue;
    }
    stream_set_timeout($conn, 20);
    smtp_write($conn, '220 simkosi.test ready');
    $secured = $mode === 'ssl';
    $authed = false;
    $data = false;
    $raw = [];
    $from = '';
    $to = '';
    while (true) {
        if ($data) {
            $chunk = [];
            while (true) {
                $line = smtp_read($conn);
                if ($line === '.') {
                    break;
                }
                if (str_starts_with($line, '..')) {
                    $line = substr($line, 1);
                }
                $chunk[] = $line;
            }
            $message = implode("\n", $chunk);
            $record = [
                'mode' => $mode,
                'from' => $from,
                'to' => $to,
                'message' => $message,
            ];
            file_put_contents($capture, json_encode($record) . "\n", FILE_APPEND);
            smtp_write($conn, '250 queued');
            $data = false;
            continue;
        }
        $line = smtp_read($conn);
        if ($line === '') {
            break;
        }
        $upper = strtoupper($line);
        if (str_starts_with($upper, 'EHLO') || str_starts_with($upper, 'HELO')) {
            smtp_write($conn, '250-simkosi.test');
            if (!$secured && $mode === 'starttls') {
                smtp_write($conn, '250-STARTTLS');
            }
            smtp_write($conn, '250 AUTH LOGIN');
            continue;
        }
        if ($upper === 'STARTTLS') {
            smtp_write($conn, '220 go ahead');
            if (!stream_socket_enable_crypto($conn, true, smtp_crypto_server())) {
                break;
            }
            $secured = true;
            continue;
        }
        if ($upper === 'AUTH LOGIN') {
            smtp_write($conn, '334 VXNlcm5hbWU6');
            $gotUser = base64_decode(smtp_read($conn), true);
            smtp_write($conn, '334 UGFzc3dvcmQ6');
            $gotPass = base64_decode(smtp_read($conn), true);
            if ($gotUser === $user && $gotPass === $pass) {
                $authed = true;
                smtp_write($conn, '235 authenticated');
            } else {
                smtp_write($conn, '535 denied');
            }
            continue;
        }
        if (str_starts_with($upper, 'MAIL FROM:')) {
            $from = trim(substr($line, 10));
            smtp_write($conn, '250 ok');
            continue;
        }
        if (str_starts_with($upper, 'RCPT TO:')) {
            $to = trim(substr($line, 8));
            smtp_write($conn, '250 ok');
            continue;
        }
        if ($upper === 'DATA') {
            if (!$authed) {
                smtp_write($conn, '530 auth required');
                continue;
            }
            smtp_write($conn, '354 end with dot');
            $data = true;
            continue;
        }
        if ($upper === 'QUIT') {
            smtp_write($conn, '221 bye');
            break;
        }
        smtp_write($conn, '250 ok');
    }
    fclose($conn);
}
