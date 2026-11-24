<?php
declare(strict_types=1);

/*
 * Project workspaces (P0 #1). A project has a name, custom instructions, saved files and its chats.
 *   - Instructions are added to the system prompt of every chat sent with body.project_id.
 *   - Project files are saved-library files added to one xAI Collection per project, searched in chat
 *     with the Responses file_search tool (vector_store_ids = [collection_id]).
 *   - Owner-only: every row is read with user_id; another account's project reads as 404.
 *   - Caps (config 'projects' => [...]): max_projects 50, max_files 20 per project; file size is the library cap.
 * Flag: platform.projects (off by default). Collections need config 'xai_management_key'.
 */

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/library.php';

function simko_projects_migrate(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;
    $db = simko_db();
    $db->exec(
        'CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            instructions TEXT NOT NULL DEFAULT \'\',
            collection_id TEXT NOT NULL DEFAULT \'\',
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )'
    );
    $db->exec('CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id, updated_at)');
    $db->exec(
        'CREATE TABLE IF NOT EXISTS project_files (
            project_id INTEGER NOT NULL,
            file_id TEXT NOT NULL,
            added_at INTEGER NOT NULL,
            PRIMARY KEY (project_id, file_id)
        )'
    );
    simko_add_column($db, 'chats', 'project_id', 'INTEGER NULL');
    simko_library_migrate();
}

function simko_projects_limits(): array
{
    $raw = simko_config_or_empty()['projects'] ?? [];
    $raw = is_array($raw) ? $raw : [];
    return [
        'max_projects' => max(1, min(500, (int) ($raw['max_projects'] ?? 50))),
        'max_files' => max(1, min(100, (int) ($raw['max_files'] ?? 20))),
        'max_instructions' => 4000,
    ];
}

function simko_project_owned(int $userId, int $projectId): ?array
{
    simko_projects_migrate();
    if ($projectId <= 0) {
        return null;
    }
    $stmt = simko_db()->prepare('SELECT * FROM projects WHERE id = ? AND user_id = ?');
    $stmt->execute([$projectId, $userId]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function simko_project_require(int $userId, int $projectId): array
{
    $row = simko_project_owned($userId, $projectId);
    if (!$row) {
        simko_fail(404, 'That project was not found.');
    }
    return $row;
}

function simko_project_public(array $row, bool $detail = false): array
{
    $db = simko_db();
    $id = (int) $row['id'];
    $files = $db->prepare('SELECT COUNT(*) FROM project_files WHERE project_id = ?');
    $files->execute([$id]);
    $chats = $db->prepare('SELECT COUNT(*) FROM chats WHERE project_id = ? AND user_id = ?');
    $chats->execute([$id, (int) $row['user_id']]);
    $out = [
        'id' => $id,
        'name' => (string) $row['name'],
        'instructions' => (string) $row['instructions'],
        'file_count' => (int) $files->fetchColumn(),
        'chat_count' => (int) $chats->fetchColumn(),
        'search_ready' => (string) $row['collection_id'] !== '',
        'created_at' => (int) $row['created_at'],
        'updated_at' => (int) $row['updated_at'],
    ];
    if ($detail) {
        $stmt = $db->prepare('SELECT f.* FROM project_files pf JOIN library_files f ON f.id = pf.file_id AND f.user_id = ? WHERE pf.project_id = ? ORDER BY pf.added_at');
        $stmt->execute([(int) $row['user_id'], $id]);
        $out['files'] = array_map('simko_library_public', $stmt->fetchAll());
        $stmt = $db->prepare('SELECT id, title, updated_at FROM chats WHERE project_id = ? AND user_id = ? ORDER BY updated_at DESC LIMIT 100');
        $stmt->execute([$id, (int) $row['user_id']]);
        $out['chats'] = array_map(static fn ($c) => ['id' => (string) $c['id'], 'title' => (string) $c['title'], 'updated_at' => (int) $c['updated_at']], $stmt->fetchAll());
    }
    return $out;
}

function simko_projects_list(int $userId): array
{
    simko_projects_migrate();
    $stmt = simko_db()->prepare('SELECT * FROM projects WHERE user_id = ? ORDER BY updated_at DESC, id DESC');
    $stmt->execute([$userId]);
    return array_map(static fn ($r) => simko_project_public($r), $stmt->fetchAll());
}

function simko_project_save(int $userId, array $body): array
{
    simko_projects_migrate();
    $limits = simko_projects_limits();
    $name = trim(preg_replace('/\s+/u', ' ', (string) ($body['name'] ?? '')) ?? '');
    if ($name === '') {
        simko_fail(400, 'Give the project a name.');
    }
    $name = simko_clip($name, 80);
    $instructions = trim((string) ($body['instructions'] ?? ''));
    if (simko_len($instructions) > $limits['max_instructions']) {
        simko_fail(400, 'Project instructions can be up to ' . $limits['max_instructions'] . ' characters.');
    }
    $db = simko_db();
    $now = time();
    $id = (int) ($body['id'] ?? 0);
    if ($id > 0) {
        simko_project_require($userId, $id);
        $db->prepare('UPDATE projects SET name = ?, instructions = ?, updated_at = ? WHERE id = ? AND user_id = ?')
            ->execute([$name, $instructions, $now, $id, $userId]);
        return simko_project_require($userId, $id);
    }
    $count = $db->prepare('SELECT COUNT(*) FROM projects WHERE user_id = ?');
    $count->execute([$userId]);
    if ((int) $count->fetchColumn() >= $limits['max_projects']) {
        simko_fail(409, 'You can have up to ' . $limits['max_projects'] . ' projects. Delete one to start another.', ['cap' => 'projects']);
    }
    $db->prepare('INSERT INTO projects (user_id, name, instructions, created_at, updated_at) VALUES (?, ?, ?, ?, ?)')
        ->execute([$userId, $name, $instructions, $now, $now]);
    return simko_project_require($userId, (int) $db->lastInsertId());
}

function simko_project_delete(int $userId, int $projectId): void
{
    $row = simko_project_require($userId, $projectId);
    if ((string) $row['collection_id'] !== '') {
        simko_xai_collection_delete((string) $row['collection_id']);
    }
    $db = simko_db();
    $db->prepare('UPDATE chats SET project_id = NULL WHERE project_id = ? AND user_id = ?')->execute([$projectId, $userId]);
    $db->prepare('DELETE FROM project_files WHERE project_id = ?')->execute([$projectId]);
    $db->prepare('DELETE FROM projects WHERE id = ? AND user_id = ?')->execute([$projectId, $userId]);
}

function simko_project_file_add(array $user, int $projectId, string $fileId): array
{
    $userId = (int) $user['id'];
    $project = simko_project_require($userId, $projectId);
    $file = simko_library_require($userId, $fileId);
    $db = simko_db();
    $has = $db->prepare('SELECT 1 FROM project_files WHERE project_id = ? AND file_id = ?');
    $has->execute([$projectId, $fileId]);
    if ($has->fetchColumn()) {
        return simko_project_require($userId, $projectId);
    }
    $limits = simko_projects_limits();
    $count = $db->prepare('SELECT COUNT(*) FROM project_files WHERE project_id = ?');
    $count->execute([$projectId]);
    if ((int) $count->fetchColumn() >= $limits['max_files']) {
        simko_fail(409, 'A project can hold up to ' . $limits['max_files'] . ' files.', ['cap' => 'project_files']);
    }
    if (!simko_xai_collections_ready()) {
        simko_fail(503, 'Project file search is not set up on this server yet.');
    }
    simko_require_grok_user($user);
    $collection = (string) $project['collection_id'];
    if ($collection === '') {
        $collection = simko_xai_collection_create('simkosi-u' . $userId . '-p' . $projectId);
        if ($collection === '') {
            simko_fail(502, 'Simko SI could not set up file search for this project. Try again in a moment.');
        }
        $db->prepare('UPDATE projects SET collection_id = ? WHERE id = ? AND user_id = ?')->execute([$collection, $projectId, $userId]);
    }
    if (!simko_xai_collection_add($collection, (string) $file['xai_file_id'])) {
        simko_fail(502, 'Simko SI could not add that file to the project. Try again in a moment.');
    }
    $now = time();
    $db->prepare('INSERT INTO project_files (project_id, file_id, added_at) VALUES (?, ?, ?)')->execute([$projectId, $fileId, $now]);
    $db->prepare('UPDATE projects SET updated_at = ? WHERE id = ?')->execute([$now, $projectId]);
    return simko_project_require($userId, $projectId);
}

function simko_project_file_remove(int $userId, int $projectId, string $fileId): array
{
    $project = simko_project_require($userId, $projectId);
    $file = simko_library_require($userId, $fileId);
    if ((string) $project['collection_id'] !== '') {
        simko_xai_collection_remove((string) $project['collection_id'], (string) $file['xai_file_id']);
    }
    simko_db()->prepare('DELETE FROM project_files WHERE project_id = ? AND file_id = ?')->execute([$projectId, $fileId]);
    return simko_project_require($userId, $projectId);
}

/** Called when a library file is deleted: take it out of every project of that person. */
function simko_projects_forget_file(int $userId, string $fileId, string $xaiFileId): void
{
    simko_projects_migrate();
    $stmt = simko_db()->prepare('SELECT p.id, p.collection_id FROM project_files pf JOIN projects p ON p.id = pf.project_id WHERE pf.file_id = ? AND p.user_id = ?');
    $stmt->execute([$fileId, $userId]);
    foreach ($stmt->fetchAll() as $p) {
        if ((string) $p['collection_id'] !== '') {
            simko_xai_collection_remove((string) $p['collection_id'], $xaiFileId);
        }
        simko_db()->prepare('DELETE FROM project_files WHERE project_id = ? AND file_id = ?')->execute([(int) $p['id'], $fileId]);
    }
}

/** Puts one of the person's chats in one of their projects, or takes it out (project_id 0). */
function simko_project_chat_assign(int $userId, string $chatId, int $projectId): void
{
    simko_projects_migrate();
    $stmt = simko_db()->prepare('SELECT id FROM chats WHERE id = ? AND user_id = ?');
    $stmt->execute([$chatId, $userId]);
    if (!$stmt->fetchColumn()) {
        simko_fail(404, 'That chat was not found.');
    }
    if ($projectId > 0) {
        simko_project_require($userId, $projectId);
    }
    simko_db()->prepare('UPDATE chats SET project_id = ? WHERE id = ? AND user_id = ?')
        ->execute([$projectId > 0 ? $projectId : null, $chatId, $userId]);
}

/**
 * What a chat inside a project adds: a system note with the instructions and, when the project has
 * files, the file_search tool over its collection. Fails 404 for a project the person does not own.
 */
function simko_project_chat_context(int $userId, int $projectId, string $chatId = ''): array
{
    $project = simko_project_require($userId, $projectId);
    $note = 'You are working inside the person\'s project "' . (string) $project['name'] . '".';
    if (trim((string) $project['instructions']) !== '') {
        $note .= " Project instructions from the person (follow them unless they conflict with safety rules):\n" . (string) $project['instructions'];
    }
    $tools = [];
    $count = simko_db()->prepare('SELECT COUNT(*) FROM project_files WHERE project_id = ?');
    $count->execute([$projectId]);
    if ((string) $project['collection_id'] !== '' && (int) $count->fetchColumn() > 0) {
        $tools[] = ['type' => 'file_search', 'vector_store_ids' => [(string) $project['collection_id']], 'max_num_results' => 10];
        $note .= "\nThe project's files are searchable with the file_search tool; search them when the question may be answered there and say which file you used.";
    }
    if ($chatId !== '') {
        simko_db()->prepare('UPDATE chats SET project_id = ? WHERE id = ? AND user_id = ? AND project_id IS NULL')->execute([$projectId, $chatId, $userId]);
    }
    return ['note' => $note, 'tools' => $tools, 'project' => $project];
}
