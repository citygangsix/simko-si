<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/oauth.php';

$state = (string) ($_POST['state'] ?? $_GET['state'] ?? '');
$provider = (string) ($_POST['provider'] ?? $_GET['provider'] ?? '');
if ($provider === '' && $state !== '') {
    $lookup = simko_db()->prepare('SELECT provider FROM oauth_states WHERE state = ?');
    $lookup->execute([$state]);
    $provider = (string) ($lookup->fetchColumn() ?: '');
}
if ($provider === '') {
    $provider = 'google';
}
$code = (string) ($_POST['code'] ?? $_GET['code'] ?? '');
$result = simko_oauth_finish($provider, $code, $state, $_POST);
header('Content-Type: text/html; charset=utf-8');
$email = htmlspecialchars($result['email'], ENT_QUOTES, 'UTF-8');
if (!empty($result['twofa_challenge'])) {
    // Two-step sign-in is on: the page asks for the code before any session exists.
    echo '<!DOCTYPE html><html><body><p>One more step for ' . $email . '.</p>'
        . '<script>try{sessionStorage.setItem("simkoTwofaChallenge",' . json_encode($result['twofa_challenge']) . ')}catch(e){}location.replace("/");</script>'
        . '</body></html>';
    exit;
}
echo '<!DOCTYPE html><html><body><p>Signed in as ' . $email . '.</p>'
    . '<script>try{sessionStorage.setItem("podcoderToken",' . json_encode($result['token']) . ')}catch(e){}location.replace("/");</script>'
    . '</body></html>';
