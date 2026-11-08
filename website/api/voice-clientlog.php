<?php
declare(strict_types=1);
// Proposed temporary voice diagnostic endpoint. Not deployed by this staging task.
require __DIR__ . '/bootstrap.php';
$body = simko_require_post_json();
$user = simko_require_user();
$stages = ['mic_request','mic_ready','mic_error','recorder_start','recorder_stop','webspeech_start','webspeech_error','transcribe_sent','transcribe_reply','transcribe_error','transcript_submit','turn_sent','turn_reply','turn_error','tts_fetch','tts_http_error','tts_audio_ready','tts_element_started','tts_webaudio_started','tts_fallback','closed'];
$errors = ['', 'NotAllowedError','SecurityError','NotFoundError','NotReadableError','AbortError','TypeError','InvalidStateError','NotSupportedError','no-speech','network','empty','unknown'];
$stage = $body['stage'] ?? '';
$error = $body['error'] ?? '';
if (!is_string($stage) || !in_array($stage, $stages, true) || !is_string($error) || !in_array($error, $errors, true)) {
    simko_fail(400, 'Unknown voice diagnostic code.');
}
// Strictly select fields. Ignore all other client values, including tokens.
$status = is_numeric($body['status'] ?? null) ? (int) $body['status'] : 0;
if ($status !== 0 && ($status < 100 || $status > 599)) $status = 0;
$path = simko_private_dir() . '/data/voice-client.log';
clearstatcache(true, $path);
// Bound this temporary log without rotating or deleting any existing data.
if (!is_file($path) || filesize($path) < 1048576) {
    $line = json_encode(['at' => gmdate('c'), 'user_id' => (int) $user['id'], 'version' => 'voice-v4', 'stage' => $stage, 'error' => $error, 'status' => $status], JSON_UNESCAPED_SLASHES) . "\n";
    @file_put_contents($path, $line, FILE_APPEND | LOCK_EX);
}
http_response_code(204);
exit;
