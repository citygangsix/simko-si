<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/agents.php';

function simko_template_create(int $userId, int $agentId): array
{
    $agent = simko_agent_owned($userId, $agentId);
    if (!$agent) {
        simko_fail(404, 'That agent is not on this account.');
    }
    $token = bin2hex(random_bytes(24));
    $payload = json_encode(['name' => $agent['name'], 'persona' => $agent['persona']], JSON_UNESCAPED_UNICODE);
    simko_db()->prepare(
        'INSERT INTO templates (token, user_id, payload, revoked, created_at) VALUES (?, ?, ?, 0, ?)'
    )->execute([$token, $userId, $payload, time()]);
    $site = rtrim((string) (simko_config_or_empty()['site_url'] ?? 'https://simkosi.com'), '/');
    return ['token' => $token, 'url' => $site . '/api/template?token=' . $token];
}

function simko_template_public(string $token): ?array
{
    if (!preg_match('/^[a-f0-9]{48}$/', $token)) {
        return null;
    }
    $stmt = simko_db()->prepare('SELECT payload, revoked FROM templates WHERE token = ?');
    $stmt->execute([$token]);
    $row = $stmt->fetch();
    if (!$row || (int) $row['revoked'] === 1) {
        return null;
    }
    $payload = json_decode((string) $row['payload'], true);
    return is_array($payload) ? $payload : null;
}

function simko_team_invite(int $userId, string $email, string $role): array
{
    $email = strtolower(trim($email));
    if (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        simko_fail(400, 'Enter the teammate email.');
    }
    if (!in_array($role, ['co-parent', 'teammate'], true)) {
        simko_fail(400, 'The role is co-parent or teammate.');
    }
    $token = bin2hex(random_bytes(24));
    simko_db()->prepare(
        'INSERT INTO team_invites (token, owner_id, email, role, created_at) VALUES (?, ?, ?, ?, ?)'
    )->execute([$token, $userId, $email, $role, time()]);
    return ['token' => $token, 'email' => $email, 'role' => $role];
}

function simko_team_accept(int $userId, string $email, string $token): array
{
    $stmt = simko_db()->prepare('SELECT owner_id, email, role FROM team_invites WHERE token = ?');
    $stmt->execute([$token]);
    $row = $stmt->fetch();
    if (!$row || strtolower((string) $row['email']) !== strtolower($email)) {
        simko_fail(404, 'That invite is not for this account.');
    }
    simko_db()->prepare(
        'INSERT OR REPLACE INTO team_members (owner_id, member_id, role, created_at) VALUES (?, ?, ?, ?)'
    )->execute([(int) $row['owner_id'], $userId, $row['role'], time()]);
    simko_db()->prepare('DELETE FROM team_invites WHERE token = ?')->execute([$token]);
    return ['role' => $row['role'], 'owner_id' => (int) $row['owner_id']];
}

function simko_team_members(int $userId): array
{
    $stmt = simko_db()->prepare(
        'SELECT m.role, u.email FROM team_members m JOIN users u ON u.id = m.member_id WHERE m.owner_id = ? ORDER BY m.created_at'
    );
    $stmt->execute([$userId]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = ['email' => $row['email'], 'role' => $row['role']];
    }
    return $rows;
}
