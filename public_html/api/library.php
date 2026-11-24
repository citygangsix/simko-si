<?php
declare(strict_types=1);

/*
 * Saved file library (P0 #2). Upload a file once, reuse it in any chat or project.
 *   - Bytes are kept in the private data folder (data/library/u<user id>/<id>.bin, never under public_html)
 *     and uploaded once to xAI Files; chats reference it with an input_file / input_image part by file_id.
 *   - Owner-only: every query filters on user_id; another account's id reads as "not found" (404).
 *   - Caps (simkosi-private/config.php 'library' => [...]): max_file_mb 25, max_total_mb 200, max_files 200.
 *   - Same bytes saved twice by one account return the first copy (sha256 dedupe), with no second upload.
 * Flag: platform.library (off by default).
 */

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/files.php';
require_once __DIR__ . '/xai-files.php';

function simko_library_migrate(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    $db = simko_db();
    $db->exec(
        'CREATE TABLE IF NOT EXISTS library_files (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            mime TEXT NOT NULL,
            kind TEXT NOT NULL,
            bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            xai_file_id TEXT NOT NULL DEFAULT \'\',
            use_count INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            last_used_at INTEGER
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_library_files_user ON library_files(user_id, created_at)');
    $db->exec('CREATE UNIQUE INDEX IF NOT EXISTS idx_library_files_sha ON library_files(user_id, sha256)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS message_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            chat_id TEXT NOT NULL DEFAULT \'\',
            file_id TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_message_files_file ON message_files(file_id)');
}

function simko_library_limits(): array
{
    $raw = simko_config_or_empty()['library'] ?? [];
    $raw = is_array($raw) ? $raw : [];
    $fileMb = max(1, min(100, (int) ($raw['max_file_mb'] ?? 25)));
    $totalMb = max($fileMb, min(5000, (int) ($raw['max_total_mb'] ?? 200)));
    return [
        'max_file_bytes' => $fileMb * 1048576,
        'max_total_bytes' => $totalMb * 1048576,
        'max_files' => max(1, min(2000, (int) ($raw['max_files'] ?? 200))),
    ];
}

function simko_library_dir(int $userId): string
{
    $dir = simko_private_dir() . '/data/library/u' . $userId;
    if (!is_dir($dir)) {
        @mkdir($dir, 0750, true);
    }
    return $dir;
}

function simko_library_kind(string $mime): string
{
    if (str_starts_with($mime, 'image/')) {
        return 'picture';
    }
    if (str_contains($mime, 'spreadsheet') || $mime === 'text/csv') {
        return 'sheet';
    }
    if ($mime === 'text/plain') {
        return 'text';
    }
    return 'document';
}

function simko_library_public(array $row): array
{
    return [
        'id' => (string) $row['id'],
        'name' => (string) $row['name'],
        'mime' => (string) $row['mime'],
        'kind' => (string) $row['kind'],
        'bytes' => (int) $row['bytes'],
        'ready' => (string) $row['xai_file_id'] !== '',
        'use_count' => (int) $row['use_count'],
        'created_at' => (int) $row['created_at'],
        'last_used_at' => $row['last_used_at'] === null ? null : (int) $row['last_used_at'],
    ];
}

function simko_library_usage(int $userId): array
{
    simko_library_migrate();
    $stmt = simko_db()->prepare('SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS b FROM library_files WHERE user_id = ?');
    $stmt->execute([$userId]);
    $row = $stmt->fetch() ?: ['n' => 0, 'b' => 0];
    $limits = simko_library_limits();
    return [
        'files' => (int) $row['n'],
        'bytes' => (int) $row['b'],
        'max_files' => $limits['max_files'],
        'max_bytes' => $limits['max_total_bytes'],
        'max_file_bytes' => $limits['max_file_bytes'],
    ];
}

/** One file row the person owns, or null (another account's file is treated as missing). */
function simko_library_owned(int $userId, string $fileId): ?array
{
    simko_library_migrate();
    if (!preg_match('/^[a-f0-9]{24}$/', $fileId)) {
        return null;
    }
    $stmt = simko_db()->prepare('SELECT * FROM library_files WHERE id = ? AND user_id = ?');
    $stmt->execute([$fileId, $userId]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function simko_library_require(int $userId, string $fileId): array
{
    $row = simko_library_owned($userId, $fileId);
    if (!$row) {
        simko_fail(404, 'That saved file was not found.');
    }
    return $row;
}

function simko_library_list(int $userId, string $query = '', string $kind = ''): array
{
    simko_library_migrate();
    $sql = 'SELECT * FROM library_files WHERE user_id = ?';
    $args = [$userId];
    if ($query !== '') {
        $sql .= ' AND name LIKE ? ESCAPE \'\\\'';
        $args[] = '%' . addcslashes(mb_substr($query, 0, 80), '%_\\') . '%';
    }
    if (in_array($kind, ['document', 'picture', 'sheet', 'text'], true)) {
        $sql .= ' AND kind = ?';
        $args[] = $kind;
    }
    $sql .= ' ORDER BY COALESCE(last_used_at, created_at) DESC LIMIT 500';
    $stmt = simko_db()->prepare($sql);
    $stmt->execute($args);
    return array_map('simko_library_public', $stmt->fetchAll());
}

/** body: {name, data (base64 or data URL)}. Returns [row, deduped]. */
function simko_library_save(array $user, array $raw): array
{
    simko_library_migrate();
    $userId = (int) $user['id'];
    $limits = simko_library_limits();
    $name = trim(preg_replace('/[^\w .()\-]+/u', '_', (string) ($raw['name'] ?? 'file')) ?? 'file');
    $name = $name === '' ? 'file' : simko_clip($name, 120);
    $b64 = (string) ($raw['data'] ?? '');
    if (str_starts_with($b64, 'data:') && str_contains($b64, ',')) {
        $b64 = substr($b64, strpos($b64, ',') + 1);
    }
    $mb = (int) ($limits['max_file_bytes'] / 1048576);
    if ($b64 === '' || strlen($b64) > (int) ceil($limits['max_file_bytes'] * 4 / 3) + 8) {
        simko_fail(413, 'That file is too big. Save a file under ' . $mb . ' MB.', ['cap' => 'file_size']);
    }
    $bytes = base64_decode($b64, true);
    if (!is_string($bytes) || $bytes === '') {
        simko_fail(400, 'That file could not be read.');
    }
    if (strlen($bytes) > $limits['max_file_bytes']) {
        simko_fail(413, 'That file is too big. Save a file under ' . $mb . ' MB.', ['cap' => 'file_size']);
    }
    $mime = simko_attach_sniff($bytes, $name);
    if ($mime === 'application/octet-stream') {
        simko_fail(415, 'That file type is not supported. Save a PDF, Word or Excel file, a text file, or a JPEG/PNG picture.');
    }
    $sha = hash('sha256', $bytes);
    $db = simko_db();
    $stmt = $db->prepare('SELECT * FROM library_files WHERE user_id = ? AND sha256 = ?');
    $stmt->execute([$userId, $sha]);
    $existing = $stmt->fetch();
    if ($existing) {
        return [$existing, true];
    }
    $usage = simko_library_usage($userId);
    if ($usage['files'] >= $limits['max_files']) {
        simko_fail(409, 'Your library is full (' . $limits['max_files'] . ' files). Delete a file to save a new one.', ['cap' => 'file_count']);
    }
    if ($usage['bytes'] + strlen($bytes) > $limits['max_total_bytes']) {
        simko_fail(409, 'Your library is full (' . (int) ($limits['max_total_bytes'] / 1048576) . ' MB). Delete a file to save a new one.', ['cap' => 'total_size']);
    }
    simko_require_grok_user($user);
    $xaiId = simko_xai_file_upload($bytes, $name, $mime);
    if ($xaiId === '') {
        simko_fail(502, 'Simko SI could not save that file with Grok. Try again in a moment.');
    }
    $id = bin2hex(random_bytes(12));
    $path = simko_library_dir($userId) . '/' . $id . '.bin';
    if (@file_put_contents($path, $bytes) === false) {
        simko_xai_file_delete($xaiId);
        simko_fail(500, 'Simko SI could not store that file.');
    }
    @chmod($path, 0640);
    $now = time();
    $db->prepare('INSERT INTO library_files (id, user_id, name, mime, kind, bytes, sha256, xai_file_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)')
        ->execute([$id, $userId, $name, $mime, simko_library_kind($mime), strlen($bytes), $sha, $xaiId, $now]);
    return [simko_library_owned($userId, $id), false];
}

function simko_library_rename(int $userId, string $fileId, string $name): array
{
    simko_library_require($userId, $fileId);
    $name = trim(preg_replace('/[^\w .()\-]+/u', '_', $name) ?? '');
    if ($name === '') {
        simko_fail(400, 'Give the file a name.');
    }
    simko_db()->prepare('UPDATE library_files SET name = ? WHERE id = ? AND user_id = ?')->execute([simko_clip($name, 120), $fileId, $userId]);
    return simko_library_owned($userId, $fileId);
}

function simko_library_delete(int $userId, string $fileId): void
{
    $row = simko_library_require($userId, $fileId);
    if (function_exists('simko_projects_forget_file')) {
        simko_projects_forget_file($userId, $fileId, (string) $row['xai_file_id']);
    }
    simko_xai_file_delete((string) $row['xai_file_id']);
    @unlink(simko_library_dir($userId) . '/' . $fileId . '.bin');
    $db = simko_db();
    $db->prepare('DELETE FROM message_files WHERE file_id = ? AND user_id = ?')->execute([$fileId, $userId]);
    $db->prepare('DELETE FROM library_files WHERE id = ? AND user_id = ?')->execute([$fileId, $userId]);
}

/**
 * Content parts for saved files picked in the chat composer (Responses API only).
 * Every id must belong to the person; up to 4 per message.
 */
function simko_library_chat_parts(int $userId, array $ids, string $chatId = ''): array
{
    $ids = array_values(array_unique(array_map('strval', $ids)));
    if (count($ids) > 4) {
        simko_fail(400, 'Pick up to 4 saved files per message.');
    }
    $parts = [];
    $now = time();
    $db = simko_db();
    foreach ($ids as $id) {
        $row = simko_library_require($userId, $id);
        if ((string) $row['xai_file_id'] === '') {
            simko_fail(409, 'That saved file is not ready yet.');
        }
        $parts[] = $row['kind'] === 'picture'
            ? ['type' => 'input_image', 'file_id' => (string) $row['xai_file_id']]
            : ['type' => 'input_file', 'file_id' => (string) $row['xai_file_id']];
        $db->prepare('UPDATE library_files SET use_count = use_count + 1, last_used_at = ? WHERE id = ? AND user_id = ?')->execute([$now, $id, $userId]);
        $db->prepare('INSERT INTO message_files (user_id, chat_id, file_id, created_at) VALUES (?, ?, ?, ?)')->execute([$userId, simko_clip($chatId, 80), $id, $now]);
    }
    return $parts;
}

/** Adds saved-file parts in front of the text of a Responses user message. */
function simko_library_merge_content(string|array $content, array $parts): array
{
    if (is_string($content)) {
        $content = [['type' => 'input_text', 'text' => $content]];
    }
    return array_merge($parts, $content);
}
