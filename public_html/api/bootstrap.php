<?php
declare(strict_types=1);

/**
 * Shared setup for Simko SI on Hostinger (Apache + PHP 8.x).
 * The xAI key is read from the private directory, never from public_html.
 *
 * Private directory, first match wins:
 *   1. constant SIMKOSI_PRIVATE (define it in api/private-path.php)
 *   2. environment variable SIMKOSI_PRIVATE
 *   3. sibling of public_html: dirname(__DIR__, 2) . '/simkosi-private'
 */

if (is_file(__DIR__ . '/private-path.php')) {
    require __DIR__ . '/private-path.php';
}

ini_set('display_errors', '0');
ini_set('html_errors', '0');

const SIMKO_DUMMY_HASH = '$2y$10$6MGN3GOKtcg2pQmYY18ZZuA/w2b2P3sbgDZmuZAZa3UWT2cYdRaem';

function simko_private_dir(): string
{
    if (defined('SIMKOSI_PRIVATE') && is_string(SIMKOSI_PRIVATE) && SIMKOSI_PRIVATE !== '') {
        return rtrim(SIMKOSI_PRIVATE, "/\\");
    }
    $env = getenv('SIMKOSI_PRIVATE');
    if (is_string($env) && $env !== '') {
        return rtrim($env, "/\\");
    }
    return dirname(__DIR__, 2) . '/simkosi-private';
}

if (PHP_SAPI === 'cli' && isset($_SERVER['SCRIPT_FILENAME']) && realpath((string) $_SERVER['SCRIPT_FILENAME']) === __FILE__) {
    $dir = simko_private_dir();
    echo 'private=' . $dir . PHP_EOL;
    echo 'config=' . (is_file($dir . '/config.php') ? 'yes' : 'no') . PHP_EOL;
    exit(0);
}

set_exception_handler(static function (Throwable $e): void {
    $dir = simko_private_dir() . '/data';
    if (!is_dir($dir)) {
        @mkdir($dir, 0750, true);
    }
    @file_put_contents(
        $dir . '/error.log',
        date('c') . ' ' . $e->getMessage() . ' @ ' . $e->getFile() . ':' . $e->getLine() . PHP_EOL,
        FILE_APPEND
    );
    if (!headers_sent()) {
        http_response_code(500);
        header('Content-Type: application/json; charset=utf-8');
    }
    $message = 'Simko SI hit a problem on the server. Try again in a moment.';
    echo json_encode(['ok' => false, 'error' => $message, 'everyday' => $message], JSON_UNESCAPED_UNICODE);
    exit;
});

function simko_config_path(): string
{
    return simko_private_dir() . '/config.php';
}

function simko_config_or_empty(): array
{
    $path = simko_config_path();
    if (!is_file($path)) {
        return [];
    }
    $cfg = require $path;
    return is_array($cfg) ? $cfg : [];
}

function simko_config(): array
{
    $cfg = simko_config_or_empty();
    if ($cfg === []) {
        simko_fail(500, 'Simko SI is missing its private config. Add simkosi-private/config.php on the server.');
    }
    return $cfg;
}

function simko_api_key(): string
{
    $key = trim((string) (simko_config()['xai_api_key'] ?? ''));
    if ($key === '' || str_contains($key, 'REPLACE')) {
        simko_fail(500, 'The Grok key is not set on the server yet.');
    }
    return $key;
}

function simko_xai_url(string $path): string
{
    $base = rtrim((string) (simko_config()['xai_base_url'] ?? 'https://api.x.ai/v1'), '/');
    return $base . '/' . ltrim($path, '/');
}

function simko_max_chars(): int
{
    $n = (int) (simko_config_or_empty()['max_input_chars'] ?? 8000);
    return $n > 0 ? $n : 8000;
}

function simko_len(string $value): int
{
    return function_exists('mb_strlen') ? mb_strlen($value) : strlen($value);
}

function simko_clip(string $value, int $max): string
{
    if (simko_len($value) <= $max) {
        return $value;
    }
    return function_exists('mb_substr') ? mb_substr($value, 0, $max) : substr($value, 0, $max);
}

function simko_fail(int $code, string $error, array $extra = []): void
{
    if (!headers_sent()) {
        http_response_code($code);
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
    }
    echo json_encode(array_merge([
        'ok' => false,
        'error' => $error,
        'everyday' => $error,
    ], $extra), JSON_UNESCAPED_UNICODE);
    exit;
}

function simko_ok(array $data = []): void
{
    if (!headers_sent()) {
        header('Content-Type: application/json; charset=utf-8');
        header('Cache-Control: no-store');
    }
    echo json_encode(array_merge(['ok' => true], $data), JSON_UNESCAPED_UNICODE);
    exit;
}

function simko_body(): array
{
    static $done = false;
    static $data = [];
    if ($done) {
        return $data;
    }
    $done = true;
    $raw = file_get_contents('php://input');
    if (!is_string($raw) || $raw === '') {
        return $data;
    }
    $parsed = json_decode($raw, true);
    if (!is_array($parsed)) {
        $data = ['_bad_json' => true];
        return $data;
    }
    $data = $parsed;
    return $data;
}

function simko_request_host(): string
{
    $host = strtolower((string) ($_SERVER['HTTP_HOST'] ?? ''));
    return (string) preg_replace('/:\d+$/', '', $host);
}

function simko_same_origin(): bool
{
    $host = simko_request_host();
    if ($host === '') {
        return false;
    }
    foreach ([$_SERVER['HTTP_ORIGIN'] ?? '', $_SERVER['HTTP_REFERER'] ?? ''] as $value) {
        if (!is_string($value) || $value === '') {
            continue;
        }
        $parsed = parse_url($value, PHP_URL_HOST);
        if (is_string($parsed) && strtolower($parsed) === $host) {
            return true;
        }
    }
    $origin = (string) ($_SERVER['HTTP_ORIGIN'] ?? '');
    if ($origin === '') {
        return false;
    }
    $extra = simko_config_or_empty()['extra_origins'] ?? [];
    if (!is_array($extra)) {
        return false;
    }
    foreach ($extra as $allowed) {
        if (is_string($allowed) && strcasecmp($origin, $allowed) === 0) {
            return true;
        }
    }
    return false;
}

function simko_require_same_origin(): void
{
    if (!simko_same_origin()) {
        simko_fail(403, 'Simko SI only answers this website.');
    }
}

function simko_require_post_json(): array
{
    $method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
    if ($method !== 'POST') {
        simko_fail(405, 'Simko SI only accepts a posted message.');
    }
    simko_require_same_origin();
    $type = (string) ($_SERVER['CONTENT_TYPE'] ?? $_SERVER['HTTP_CONTENT_TYPE'] ?? '');
    if (stripos($type, 'application/json') === false) {
        simko_fail(415, 'Send that as JSON.');
    }
    $body = simko_body();
    if (!empty($body['_bad_json'])) {
        simko_fail(400, 'That message could not be read. Send plain text.');
    }
    return $body;
}

function simko_https(): bool
{
    $https = strtolower((string) ($_SERVER['HTTPS'] ?? ''));
    if ($https !== '' && $https !== 'off') {
        return true;
    }
    return strtolower((string) ($_SERVER['HTTP_X_FORWARDED_PROTO'] ?? '')) === 'https';
}

function simko_set_cookie(string $token, int $expires): void
{
    setcookie('simko', $token, [
        'expires' => $expires,
        'path' => '/',
        'secure' => simko_https(),
        'httponly' => true,
        'samesite' => 'Lax',
    ]);
}

function simko_clear_cookie(): void
{
    simko_set_cookie('', time() - 42000);
}

function simko_token_candidates(): array
{
    $found = [];
    $body = simko_body();
    if (!empty($body['token']) && is_string($body['token'])) {
        $found[] = $body['token'];
    }
    if (!empty($_COOKIE['simko']) && is_string($_COOKIE['simko'])) {
        $found[] = $_COOKIE['simko'];
    }
    $header = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
    if (str_starts_with($header, 'Bearer ')) {
        $found[] = trim(substr($header, 7));
    }
    $unique = [];
    foreach ($found as $token) {
        if ($token !== '' && !in_array($token, $unique, true)) {
            $unique[] = $token;
        }
    }
    return $unique;
}

function simko_request_token(): string
{
    $tokens = simko_token_candidates();
    return $tokens[0] ?? '';
}

function simko_db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }
    if (!in_array('sqlite', PDO::getAvailableDrivers(), true)) {
        simko_fail(500, 'This PHP build has no SQLite driver.');
    }
    $dir = simko_private_dir() . '/data';
    if (!is_dir($dir) && !@mkdir($dir, 0750, true) && !is_dir($dir)) {
        simko_fail(500, 'Simko SI cannot write its private data folder.');
    }
    $pdo = new PDO('sqlite:' . $dir . '/simko.sqlite', null, null, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
    ]);
    $pdo->exec('PRAGMA journal_mode = WAL');
    $pdo->exec('PRAGMA foreign_keys = ON');
    $pdo->exec('PRAGMA busy_timeout = 3000');
    simko_migrate($pdo);
    return $pdo;
}

function simko_migrate(PDO $db): void
{
    $db->exec(
        'CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            confirmed INTEGER NOT NULL DEFAULT 0,
            confirm_token TEXT,
            reset_token TEXT,
            reset_expires INTEGER,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS auth_tokens (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            body TEXT NOT NULL,
            from_title TEXT,
            to_title TEXT,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS life_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            label TEXT NOT NULL,
            tone TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id, updated_at DESC)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_life_user ON life_events(user_id, id)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_tokens_user ON auth_tokens(user_id)');
    simko_add_column($db, 'users', 'role', "TEXT NOT NULL DEFAULT 'adult'");
    simko_add_column($db, 'users', 'parent_consent_at', 'INTEGER');
    simko_add_column($db, 'chats', 'child_profile_id', 'INTEGER');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS child_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_user_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            avatar TEXT NOT NULL,
            age_band TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS mail_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            kind TEXT NOT NULL,
            sent_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_child_parent ON child_profiles(parent_user_id, id)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_chats_child ON chats(user_id, child_profile_id, updated_at DESC)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_mail_email ON mail_log(email, sent_at)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS usage_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS subscriptions (
            user_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            trial_until INTEGER,
            square_link_id TEXT,
            updated_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_events(user_id, id)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            summary TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            decided_at INTEGER
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            summary TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_approvals_user ON approvals(user_id, id)');
    $db->exec('CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id, id)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            child_profile_id INTEGER,
            fact TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id, child_profile_id, id)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS routines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            child_profile_id INTEGER,
            kind TEXT NOT NULL,
            hour INTEGER NOT NULL,
            minute INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL
        )'
    );
    $db->exec(
        'CREATE TABLE IF NOT EXISTS routine_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routine_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            read_at INTEGER
        )'
    );
}

function simko_add_column(PDO $db, string $table, string $column, string $definition): void
{
    $allowed = [
        'users' => ['role' => true, 'parent_consent_at' => true],
        'chats' => ['child_profile_id' => true],
    ];
    if (!isset($allowed[$table][$column])) {
        return;
    }
    $info = $db->query('PRAGMA table_info(' . $table . ')');
    $rows = $info ? $info->fetchAll() : [];
    foreach ($rows as $row) {
        if (($row['name'] ?? '') === $column) {
            return;
        }
    }
    $db->exec('ALTER TABLE ' . $table . ' ADD COLUMN ' . $column . ' ' . $definition);
}

function simko_family_ui(): bool
{
    return !empty(simko_config_or_empty()['family_ui']);
}

function simko_platform_names(): array
{
    return [
        'paywall', 'approvals', 'search', 'memory', 'routines', 'images',
        'shares', 'oauth', 'vault', 'connectors', 'agents', 'team',
        'calls', 'browse', 'store',
    ];
}

function simko_flag(string $name): bool
{
    $flags = simko_config_or_empty()['platform'] ?? [];
    return is_array($flags) && !empty($flags[$name]);
}

function simko_platform_flags(): array
{
    $out = [];
    foreach (simko_platform_names() as $name) {
        $out[$name] = simko_flag($name);
    }
    return $out;
}

function simko_user_for_token(string $token): ?array
{
    if ($token === '') {
        return null;
    }
    $stmt = simko_db()->prepare(
        'SELECT u.id, u.email, u.confirmed, u.created_at, u.role, u.parent_consent_at
         FROM auth_tokens t
         JOIN users u ON u.id = t.user_id
         WHERE t.token_hash = ? AND t.expires_at > ?'
    );
    $stmt->execute([hash('sha256', $token), time()]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function simko_current_user(): ?array
{
    foreach (simko_token_candidates() as $token) {
        $user = simko_user_for_token($token);
        if ($user) {
            return $user;
        }
    }
    return null;
}

function simko_require_user(): array
{
    $user = simko_current_user();
    if (!$user) {
        simko_fail(401, 'Sign in to talk with Simko SI.');
    }
    return $user;
}

function simko_issue_token(int $userId): string
{
    $token = bin2hex(random_bytes(32));
    $stmt = simko_db()->prepare('INSERT INTO auth_tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)');
    $expires = time() + 60 * 60 * 24 * 30;
    $stmt->execute([hash('sha256', $token), $userId, $expires]);
    simko_set_cookie($token, $expires);
    return $token;
}

function simko_revoke_token(string $token): void
{
    if ($token === '') {
        return;
    }
    $stmt = simko_db()->prepare('DELETE FROM auth_tokens WHERE token_hash = ?');
    $stmt->execute([hash('sha256', $token)]);
}

function simko_child_owned(int $parentId, int $childId): ?array
{
    if ($childId < 1) {
        return null;
    }
    $stmt = simko_db()->prepare(
        'SELECT id, parent_user_id, display_name, avatar, age_band, created_at
         FROM child_profiles WHERE id = ? AND parent_user_id = ?'
    );
    $stmt->execute([$childId, $parentId]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function simko_requested_child(int $userId, array $body): ?int
{
    if (!array_key_exists('child_id', $body) || $body['child_id'] === '' || $body['child_id'] === null) {
        return null;
    }
    $childId = (int) $body['child_id'];
    if (!simko_child_owned($userId, $childId)) {
        simko_fail(404, 'That child profile is not on this account.');
    }
    return $childId;
}

function simko_chat_owned(int $userId, string $chatId): ?array
{
    if ($chatId === '' || str_starts_with($chatId, 'demo-')) {
        return null;
    }
    $stmt = simko_db()->prepare(
        'SELECT id, user_id, title, created_at, updated_at, child_profile_id FROM chats WHERE id = ? AND user_id = ?'
    );
    $stmt->execute([$chatId, $userId]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function simko_chat_messages(string $chatId): array
{
    $stmt = simko_db()->prepare(
        'SELECT role, body AS text, from_title, to_title, created_at
         FROM messages WHERE chat_id = ? ORDER BY id ASC'
    );
    $stmt->execute([$chatId]);
    return $stmt->fetchAll() ?: [];
}

function simko_public_session(array $chat, bool $withMessages): array
{
    $session = [
        'id' => $chat['id'],
        'title' => $chat['title'],
        'updated_at' => (int) $chat['updated_at'],
    ];
    if ($withMessages) {
        $session['messages'] = simko_chat_messages($chat['id']);
    }
    return $session;
}

/**
 * Optional Supabase sync. Off unless config enables the one allowed project.
 * Failures are ignored so chat never depends on it.
 */
function simko_supabase_hook(string $event, array $user): void
{
    $sb = simko_config_or_empty()['supabase'] ?? null;
    if (!is_array($sb) || empty($sb['enabled'])) {
        return;
    }
    if (($sb['project_ref'] ?? '') !== 'wxvjajecvklfjxppawdx') {
        return;
    }
    $url = rtrim((string) ($sb['url'] ?? ''), '/');
    $key = trim((string) ($sb['service_key'] ?? ''));
    if ($url === '' || $key === '' || !function_exists('curl_init')) {
        return;
    }
    $payload = json_encode([
        'event' => $event,
        'email' => (string) ($user['email'] ?? ''),
        'user_id' => (int) ($user['id'] ?? 0),
        'at' => time(),
    ], JSON_UNESCAPED_UNICODE);
    $ch = curl_init($url . '/rest/v1/simko_events');
    if ($ch === false) {
        return;
    }
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $payload,
        CURLOPT_HTTPHEADER => [
            'Content-Type: application/json',
            'apikey: ' . $key,
            'Authorization: Bearer ' . $key,
            'Prefer: return=minimal',
        ],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 4,
        CURLOPT_CONNECTTIMEOUT => 3,
        CURLOPT_FOLLOWLOCATION => false,
    ]);
    curl_exec($ch);
    curl_close($ch);
}

function simko_choice_text(array $data): string
{
    $content = $data['choices'][0]['message']['content'] ?? '';
    if (is_string($content)) {
        return trim($content);
    }
    if (!is_array($content)) {
        return '';
    }
    $parts = [];
    foreach ($content as $part) {
        if (is_string($part)) {
            $parts[] = $part;
        } elseif (is_array($part) && isset($part['text']) && is_string($part['text'])) {
            $parts[] = $part['text'];
        }
    }
    return trim(implode('', $parts));
}

function simko_curl_json(string $url, array $payload, int $timeout = 45): array
{
    $body = json_encode($payload, JSON_UNESCAPED_UNICODE);
    $result = simko_curl($url, $body, [
        'Content-Type: application/json',
        'Authorization: Bearer ' . simko_api_key(),
        'Accept: application/json',
    ], $timeout);
    $decoded = json_decode($result['body'], true);
    if (!is_array($decoded) || $result['code'] >= 400 || $result['code'] === 0) {
        simko_log_upstream($result['code'], $result['error']);
        simko_fail(502, 'Simko SI could not reach Grok. Try again in a moment.');
    }
    return $decoded;
}

function simko_curl(string $url, string|array $fields, array $headers, int $timeout): array
{
    if (!function_exists('curl_init')) {
        simko_fail(500, 'This PHP build has no curl, so Simko SI cannot reach Grok.');
    }
    $ch = curl_init($url);
    if ($ch === false) {
        simko_fail(502, 'Simko SI could not reach Grok. Try again in a moment.');
    }
    $options = [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => $fields,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_FOLLOWLOCATION => false,
    ];
    if (defined('CURLPROTO_HTTP') && defined('CURLPROTO_HTTPS')) {
        $options[CURLOPT_PROTOCOLS] = CURLPROTO_HTTP | CURLPROTO_HTTPS;
    }
    curl_setopt_array($ch, $options);
    $raw = curl_exec($ch);
    $error = curl_error($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $type = (string) curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
    curl_close($ch);
    return [
        'code' => $code,
        'body' => is_string($raw) ? $raw : '',
        'type' => $type,
        'error' => $error,
    ];
}

function simko_log_upstream(int $code, string $error): void
{
    $dir = simko_private_dir() . '/data';
    if (!is_dir($dir)) {
        return;
    }
    $line = date('c') . ' upstream ' . $code . ' ' . preg_replace('/\s+/', ' ', $error) . PHP_EOL;
    @file_put_contents($dir . '/error.log', $line, FILE_APPEND);
}
