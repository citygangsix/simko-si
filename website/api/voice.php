<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/voice-catalog.php';

$op = (string) ($_GET['op'] ?? '');

switch ($op) {
    case 'voices':
        simko_voice_list();
        break;
    case 'speak':
        simko_speak();
        break;
    case 'transcribe':
        simko_transcribe();
        break;
    default:
        simko_fail(404, 'That voice step is not on this website.');
}

function simko_voice_list(): void
{
    $voices = [];
    foreach (simko_voice_catalog() as $voice) {
        $voices[] = [
            'id' => $voice['id'],
            'name' => $voice['name'],
            'tone' => $voice['tone'],
        ];
    }
    simko_ok([
        'voices' => $voices,
        'ready' => true,
        'min_speed' => 0.7,
        'max_speed' => 1.5,
        'default_speed' => 1,
        'default_voice' => 'coral',
    ]);
}

function simko_speak(): void
{
    if (strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET')) !== 'GET') {
        simko_fail(405, 'Simko SI speaks from a voice link.');
    }
    simko_require_same_origin();
    if (!simko_current_user()) {
        simko_fail(401, 'Sign in to hear Simko SI.');
    }
    $voice = simko_voice_by_id(strtolower(trim((string) ($_GET['voice'] ?? 'coral'))));
    if (!$voice) simko_fail(400, 'Choose a voice from the voice picker.');
    $preview = isset($_GET['preview']) && (string) $_GET['preview'] !== '' && (string) $_GET['preview'] !== '0';
    $text = trim((string) ($_GET['text'] ?? ''));
    if ($preview && $text === '') {
        $text = 'Hello. I am ' . $voice['name'] . '.';
    }
    if ($text === '') {
        simko_fail(400, 'There is nothing to say.');
    }
    if (simko_len($text) > simko_max_chars()) {
        simko_fail(413, 'That line is too long to speak.');
    }
    $speed = (float) ($_GET['speed'] ?? 1);
    if ($speed < 0.7) {
        $speed = 0.7;
    }
    if ($speed > 1.5) {
        $speed = 1.5;
    }
    $result = simko_curl(simko_xai_url('tts'), json_encode([
        'text' => $text,
        'voice_id' => $voice['xai'],
        'language' => 'en',
        'speed' => $speed,
    ], JSON_UNESCAPED_UNICODE), [
        'Content-Type: application/json',
        'Authorization: Bearer ' . simko_api_key(),
        'Accept: audio/mpeg, application/json',
    ], 45);
    if ($result['code'] >= 400 || $result['body'] === '') {
        simko_log_upstream($result['code'], $result['error']);
        simko_fail(502, 'Simko SI could not speak just now. The browser voice will try.');
    }
    $type = $result['type'];
    $bytes = $result['body'];
    if (str_contains($type, 'json') || (isset($bytes[0]) && $bytes[0] === '{')) {
        $json = json_decode($bytes, true);
        if (is_array($json) && isset($json['audio']) && is_string($json['audio'])) {
            $decoded = base64_decode($json['audio'], true);
            if ($decoded === false) {
                simko_fail(502, 'Simko SI could not speak just now.');
            }
            $bytes = $decoded;
            $type = (string) ($json['content_type'] ?? 'audio/mpeg');
        } else {
            simko_fail(502, 'Simko SI could not speak just now.');
        }
    }
    if (!headers_sent()) {
        header('Content-Type: ' . ($type !== '' ? $type : 'audio/mpeg'));
        header('Cache-Control: no-store');
    }
    echo $bytes;
    exit;
}

function simko_transcribe(): void
{
    $body = simko_require_post_json();
    if (!simko_current_user()) {
        simko_fail(401, 'Sign in to use the microphone.');
    }
    $audio = (string) ($body['audio'] ?? '');
    if ($audio === '') {
        simko_fail(400, 'I did not catch that. Try the mic again.');
    }
    $binary = base64_decode($audio, true);
    if ($binary === false || $binary === '') {
        simko_fail(400, 'I did not catch that. Try the mic again.');
    }
    if (strlen($binary) > 8 * 1024 * 1024) {
        simko_fail(413, 'That recording is too long. Try a shorter take.');
    }
    $mime = (string) ($body['mime'] ?? 'audio/webm');
    if (!preg_match('#^audio/[a-z0-9.+-]+$#i', $mime)) {
        $mime = 'audio/webm';
    }
    $tmp = tempnam(sys_get_temp_dir(), 'simko');
    if ($tmp === false) {
        simko_fail(500, 'Simko SI could not hold that recording.');
    }
    file_put_contents($tmp, $binary);
    $file = new CURLFile($tmp, $mime, 'speech.webm');
    $model = (string) (simko_config()['stt_model'] ?? 'grok-voice-transcribe-2.0');
    $result = simko_curl(simko_xai_url('stt'), [
        'model' => $model,
        'language' => 'en',
        'file' => $file,
    ], [
        'Authorization: Bearer ' . simko_api_key(),
        'Accept: application/json',
    ], 45);
    @unlink($tmp);
    $decoded = json_decode($result['body'], true);
    $text = is_array($decoded) ? trim((string) ($decoded['text'] ?? '')) : '';
    if ($result['code'] >= 400 || $text === '') {
        simko_log_upstream($result['code'], $result['error']);
        simko_fail(502, 'I did not catch that. Try the mic again.');
    }
    simko_ok(['text' => $text, 'everyday' => $text]);
}
