<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

function simko_guard_approval(int $userId, array $body, string $action, string $summary, array $payload): bool
{
    if (!simko_flag('approvals')) {
        return true;
    }
    $approvalId = (int) ($body['approval_id'] ?? 0);
    if ($approvalId > 0) {
        $stmt = simko_db()->prepare(
            'SELECT id, action, status FROM approvals WHERE id = ? AND user_id = ?'
        );
        $stmt->execute([$approvalId, $userId]);
        $row = $stmt->fetch();
        if (!$row || (string) $row['action'] !== $action || (string) $row['status'] !== 'approved') {
            simko_fail(403, 'Approve that action before Simko SI will do it.');
        }
        return true;
    }
    $now = time();
    $insert = simko_db()->prepare(
        'INSERT INTO approvals (user_id, action, summary, payload, status, created_at) VALUES (?, ?, ?, ?, ?, ?)'
    );
    $insert->execute([$userId, $action, simko_clip($summary, 240), json_encode($payload), 'pending', $now]);
    simko_ok(['approval' => [
        'id' => (int) simko_db()->lastInsertId(),
        'action' => $action,
        'summary' => simko_clip($summary, 240),
    ]]);
}

function simko_audit(int $userId, string $action, string $summary): void
{
    $stmt = simko_db()->prepare(
        'INSERT INTO audit_log (user_id, action, summary, created_at) VALUES (?, ?, ?, ?)'
    );
    $stmt->execute([$userId, $action, simko_clip($summary, 240), time()]);
}

function simko_decide_approval(int $userId, int $approvalId, string $decision): array
{
    if (!in_array($decision, ['approved', 'declined'], true)) {
        simko_fail(400, 'Choose approve or decline.');
    }
    $stmt = simko_db()->prepare('SELECT id, action, summary, status FROM approvals WHERE id = ? AND user_id = ?');
    $stmt->execute([$approvalId, $userId]);
    $row = $stmt->fetch();
    if (!$row || (string) $row['status'] !== 'pending') {
        simko_fail(404, 'That approval is not waiting.');
    }
    $update = simko_db()->prepare('UPDATE approvals SET status = ?, decided_at = ? WHERE id = ?');
    $update->execute([$decision, time(), $approvalId]);
    $verb = $decision === 'approved' ? 'Approved' : 'Declined';
    simko_audit($userId, (string) $row['action'], $verb . ': ' . $row['summary']);
    return [
        'id' => $approvalId,
        'action' => $row['action'],
        'status' => $decision,
        'summary' => $row['summary'],
    ];
}

function simko_audit_rows(int $userId): array
{
    $stmt = simko_db()->prepare(
        'SELECT action, summary, created_at FROM audit_log WHERE user_id = ? ORDER BY id DESC LIMIT 40'
    );
    $stmt->execute([$userId]);
    $rows = [];
    foreach ($stmt->fetchAll() as $row) {
        $rows[] = [
            'action' => $row['action'],
            'summary' => $row['summary'],
            'created_at' => (int) $row['created_at'],
        ];
    }
    return $rows;
}
