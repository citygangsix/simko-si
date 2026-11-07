<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/oauth.php';

$provider = (string) ($_GET['provider'] ?? $_POST['provider'] ?? 'google');
$code = (string) ($_GET['code'] ?? $_POST['code'] ?? '');
$state = (string) ($_GET['state'] ?? $_POST['state'] ?? '');
$result = simko_oauth_finish($provider, $code, $state);
header('Content-Type: text/html; charset=utf-8');
$email = htmlspecialchars($result['email'], ENT_QUOTES, 'UTF-8');
$token = htmlspecialchars($result['token'], ENT_QUOTES, 'UTF-8');
echo '<!DOCTYPE html><html><body><p>Signed in as ' . $email . '.</p>'
    . '<script>try{sessionStorage.setItem("podcoderToken",' . json_encode($result['token']) . ')}catch(e){}location.replace("/");</script>'
    . '<noscript>Token ' . $token . '</noscript></body></html>';
