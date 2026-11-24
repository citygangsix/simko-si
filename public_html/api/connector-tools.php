<?php
declare(strict_types=1);

/**
 * What Grok and the person can read through a connected app.
 * Google Drive uses the drive.file scope: only files the person picked in the Google Picker.
 * GitHub: list my repos, read one file, list open issues. Everything here is read-only.
 */

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/connectors.php';

const SIMKO_TOOL_TEXT_MAX = 12000;

function simko_picks_migrate(): void
{
    simko_db()->exec(
        'CREATE TABLE IF NOT EXISTS connector_picks (
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            file_id TEXT NOT NULL,
            name TEXT NOT NULL,
            mime_type TEXT NOT NULL DEFAULT "",
            picked_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, provider, file_id)
        )'
    );
}

function simko_drive_picks(int $userId): array
{
    simko_picks_migrate();
    $st = simko_db()->prepare('SELECT file_id AS id, name, mime_type, picked_at FROM connector_picks WHERE user_id = ? AND provider = ? ORDER BY picked_at DESC, name');
    $st->execute([$userId, 'google-drive']);
    return array_map(static fn ($r) => ['id' => (string) $r['id'], 'name' => (string) $r['name'], 'mime_type' => (string) $r['mime_type'], 'picked_at' => (int) $r['picked_at']], $st->fetchAll());
}

function simko_drive_picks_save(int $userId, array $files): array
{
    if (!simko_connector_connected($userId, 'google-drive')) {
        simko_fail(404, 'Connect Google Drive first.');
    }
    simko_picks_migrate();
    $ins = simko_db()->prepare(
        'INSERT INTO connector_picks (user_id, provider, file_id, name, mime_type, picked_at) VALUES (?, ?, ?, ?, ?, ?)
         ON CONFLICT(user_id, provider, file_id) DO UPDATE SET name = excluded.name, mime_type = excluded.mime_type, picked_at = excluded.picked_at'
    );
    $saved = 0;
    foreach (array_slice($files, 0, 50) as $f) {
        $id = is_array($f) ? trim((string) ($f['id'] ?? '')) : '';
        if (!preg_match('/^[A-Za-z0-9_-]{10,200}$/', $id)) {
            continue;
        }
        $name = simko_clip(trim((string) ($f['name'] ?? 'Untitled')), 200);
        $mime = simko_clip(trim((string) ($f['mimeType'] ?? $f['mime_type'] ?? '')), 120);
        $ins->execute([$userId, 'google-drive', $id, $name === '' ? 'Untitled' : $name, $mime, time()]);
        $saved++;
    }
    return ['saved' => $saved, 'files' => simko_drive_picks($userId)];
}

function simko_drive_pick_remove(int $userId, string $fileId): array
{
    simko_picks_migrate();
    simko_db()->prepare('DELETE FROM connector_picks WHERE user_id = ? AND provider = ? AND file_id = ?')->execute([$userId, 'google-drive', $fileId]);
    return ['files' => simko_drive_picks($userId)];
}

/** What the browser needs to open the Google Picker for this person. */
function simko_drive_picker_config(int $userId): array
{
    $settings = simko_connector_settings('google-drive');
    if ($settings['picker_api_key'] === '') {
        simko_fail(404, 'The Google file picker is not set up yet.');
    }
    return [
        'access_token' => simko_connector_access_token($userId, 'google-drive'),
        'api_key' => $settings['picker_api_key'],
        'app_id' => $settings['app_id'],
    ];
}

function simko_connector_http(string $url, string $access, array $extraHeaders = [], int $timeout = 20): array
{
    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_HTTPHEADER => array_merge(['Authorization: Bearer ' . $access, 'User-Agent: SimkoSI'], $extraHeaders),
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_MAXREDIRS => 3,
        CURLOPT_TIMEOUT => $timeout,
    ]);
    $raw = curl_exec($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
    curl_close($ch);
    return [$code, is_string($raw) ? $raw : ''];
}

function simko_tool_clip(string $text): array
{
    $len = strlen($text);
    if ($len > SIMKO_TOOL_TEXT_MAX) {
        return ['text' => mb_strcut($text, 0, SIMKO_TOOL_TEXT_MAX, 'UTF-8'), 'truncated' => true, 'bytes' => $len];
    }
    return ['text' => $text, 'truncated' => false, 'bytes' => $len];
}

/** Text of one picked Drive file. Google Docs/Sheets/Slides are exported; text-like files are downloaded. */
function simko_drive_read(int $userId, string $fileId): array
{
    simko_picks_migrate();
    $st = simko_db()->prepare('SELECT name, mime_type FROM connector_picks WHERE user_id = ? AND provider = ? AND file_id = ?');
    $st->execute([$userId, 'google-drive', $fileId]);
    $pick = $st->fetch();
    if (!$pick) {
        return ['error' => 'That file was not picked. Ask the person to tap Pick files in Connectors and choose it.'];
    }
    $settings = simko_connector_settings('google-drive');
    $access = simko_connector_access_token($userId, 'google-drive');
    $base = $settings['api_base'] . '/drive/v3/files/' . rawurlencode($fileId);
    [$code, $raw] = simko_connector_http($base . '?fields=id,name,mimeType,size,modifiedTime&supportsAllDrives=true', $access);
    $meta = json_decode($raw, true);
    if ($code !== 200 || !is_array($meta)) {
        return ['error' => 'Google Drive did not return that file (HTTP ' . $code . ').'];
    }
    $mime = (string) ($meta['mimeType'] ?? '');
    $exports = [
        'application/vnd.google-apps.document' => 'text/plain',
        'application/vnd.google-apps.spreadsheet' => 'text/csv',
        'application/vnd.google-apps.presentation' => 'text/plain',
    ];
    if (isset($exports[$mime])) {
        [$code, $body] = simko_connector_http($base . '/export?mimeType=' . rawurlencode($exports[$mime]), $access);
    } elseif (preg_match('#^(text/|application/(json|xml|javascript|x-yaml|csv))#', $mime) || preg_match('/\.(txt|md|csv|json|ya?ml|xml|html?|js|ts|py|php|log)$/i', (string) $meta['name'])) {
        if ((int) ($meta['size'] ?? 0) > 2000000) {
            return ['error' => 'That file is over 2 MB, too big to read here.'];
        }
        [$code, $body] = simko_connector_http($base . '?alt=media&supportsAllDrives=true', $access);
    } else {
        return ['name' => (string) $meta['name'], 'mime_type' => $mime, 'error' => 'Simko SI can read Google Docs, Sheets, Slides and text files. This is ' . ($mime ?: 'an unknown type') . '.'];
    }
    if ($code !== 200) {
        return ['error' => 'Google Drive would not export that file (HTTP ' . $code . ').'];
    }
    if (!mb_check_encoding($body, 'UTF-8')) {
        $body = mb_convert_encoding($body, 'UTF-8', 'UTF-8');
    }
    return ['name' => (string) $meta['name'], 'mime_type' => $mime, 'modified' => (string) ($meta['modifiedTime'] ?? '')] + simko_tool_clip($body);
}

function simko_github_get(int $userId, string $path): array
{
    $settings = simko_connector_settings('github');
    $access = simko_connector_access_token($userId, 'github');
    [$code, $raw] = simko_connector_http($settings['api_base'] . $path, $access, ['Accept: application/vnd.github+json', 'X-GitHub-Api-Version: 2022-11-28']);
    $data = json_decode($raw, true);
    return [$code, is_array($data) ? $data : null];
}

function simko_github_safe(string $value, string $pattern): string
{
    $value = trim($value);
    return preg_match($pattern, $value) ? $value : '';
}

function simko_github_list_repos(int $userId): array
{
    [$code, $data] = simko_github_get($userId, '/user/repos?sort=updated&per_page=30');
    if ($code !== 200 || !is_array($data)) {
        return ['error' => 'GitHub did not list the repositories (HTTP ' . $code . ').'];
    }
    return ['repos' => array_map(static fn ($r) => [
        'full_name' => (string) ($r['full_name'] ?? ''),
        'private' => !empty($r['private']),
        'description' => simko_clip((string) ($r['description'] ?? ''), 200),
        'default_branch' => (string) ($r['default_branch'] ?? ''),
        'updated_at' => (string) ($r['updated_at'] ?? ''),
    ], array_slice($data, 0, 30))];
}

function simko_github_read_file(int $userId, string $repo, string $path, string $ref = ''): array
{
    $repo = simko_github_safe($repo, '#^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$#');
    $path = ltrim(trim($path), '/');
    if ($repo === '' || $path === '' || str_contains($path, '..') || !preg_match('#^[A-Za-z0-9_./ -]+$#', $path)) {
        return ['error' => 'Give the repository as owner/name and a file path.'];
    }
    $url = '/repos/' . $repo . '/contents/' . implode('/', array_map('rawurlencode', explode('/', $path)));
    if ($ref !== '' && preg_match('#^[A-Za-z0-9_./-]{1,100}$#', $ref)) {
        $url .= '?ref=' . rawurlencode($ref);
    }
    [$code, $data] = simko_github_get($userId, $url);
    if ($code !== 200 || !is_array($data)) {
        return ['error' => 'GitHub did not return that file (HTTP ' . $code . ').'];
    }
    if (isset($data[0]) || ($data['type'] ?? '') !== 'file') {
        $names = isset($data[0]) ? array_map(static fn ($e) => ($e['type'] ?? '') === 'dir' ? $e['name'] . '/' : (string) ($e['name'] ?? ''), $data) : [];
        return ['error' => 'That path is a folder, not a file.', 'entries' => array_slice($names, 0, 100)];
    }
    $text = base64_decode(str_replace("\n", '', (string) ($data['content'] ?? '')), true);
    if (!is_string($text) || !mb_check_encoding($text, 'UTF-8')) {
        return ['error' => 'That file is not text.'];
    }
    return ['repo' => $repo, 'path' => $path] + simko_tool_clip($text);
}

function simko_github_list_issues(int $userId, string $repo): array
{
    $repo = simko_github_safe($repo, '#^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$#');
    if ($repo === '') {
        return ['error' => 'Give the repository as owner/name.'];
    }
    [$code, $data] = simko_github_get($userId, '/repos/' . $repo . '/issues?state=open&per_page=30');
    if ($code !== 200 || !is_array($data)) {
        return ['error' => 'GitHub did not list issues (HTTP ' . $code . ').'];
    }
    $out = [];
    foreach ($data as $i) {
        if (isset($i['pull_request'])) {
            continue;
        }
        $out[] = ['number' => (int) ($i['number'] ?? 0), 'title' => simko_clip((string) ($i['title'] ?? ''), 200), 'user' => (string) ($i['user']['login'] ?? ''), 'created_at' => (string) ($i['created_at'] ?? '')];
    }
    return ['repo' => $repo, 'issues' => $out];
}
