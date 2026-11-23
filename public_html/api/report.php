<?php
declare(strict_types=1);

/**
 * "Report this reply" for AI answers (Google Play AI-generated content policy; also helps Apple 1.2).
 * Stores the report in simkosi-private/data/ai-reports.jsonl (outside the web root). No database change.
 */
require __DIR__ . '/bootstrap.php';

$body = simko_require_post_json();
$reasons = ['offensive', 'sexual', 'violent', 'hateful', 'dangerous', 'false', 'privacy', 'other'];
$reason = (string) ($body['reason'] ?? '');
if (!in_array($reason, $reasons, true)) {
    simko_fail(400, 'Pick a reason for the report.');
}
$reply = simko_clip(trim((string) ($body['reply'] ?? '')), 4000);
if ($reply === '') {
    simko_fail(400, 'There is no reply to report yet.');
}
$note = simko_clip(trim((string) ($body['note'] ?? '')), 1000);
$chatId = preg_replace('/[^A-Za-z0-9_-]/', '', (string) ($body['chat_id'] ?? '')) ?? '';
$user = simko_current_user();

$dir = simko_private_dir() . '/data';
if (!is_dir($dir)) {
    @mkdir($dir, 0700, true);
}
$ipKey = hash('sha256', (string) ($_SERVER['REMOTE_ADDR'] ?? '') . gmdate('Y-m-d'));
$limitFile = $dir . '/ai-report-limits.json';
$limits = is_file($limitFile) ? (json_decode((string) file_get_contents($limitFile), true) ?: []) : [];
$today = gmdate('Y-m-d');
if (($limits['day'] ?? '') !== $today) {
    $limits = ['day' => $today, 'n' => []];
}
$limits['n'][$ipKey] = (int) ($limits['n'][$ipKey] ?? 0) + 1;
if ($limits['n'][$ipKey] > 30) {
    simko_fail(429, 'Thanks. We already have your reports for today.');
}
@file_put_contents($limitFile, json_encode($limits), LOCK_EX);

$row = [
    'at' => gmdate('c'),
    'user_id' => $user ? (int) $user['id'] : null,
    'chat_id' => $chatId,
    'reason' => $reason,
    'note' => $note,
    'reply' => $reply,
];
$ok = @file_put_contents($dir . '/ai-reports.jsonl', json_encode($row, JSON_UNESCAPED_UNICODE) . "\n", FILE_APPEND | LOCK_EX);
if ($ok === false) {
    simko_fail(500, 'The report could not be saved. Try again.');
}
simko_ok(['reported' => true]);
