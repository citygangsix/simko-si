<?php
declare(strict_types=1);

require_once __DIR__ . '/bootstrap.php';

/*
 * In-chat Yes/No approval cards (spec: simkosi-ops/p0-backend/APPROVAL-PROMPT-SPEC.md).
 *  - A card is a row in `approvals` (pending). Its display facts (title, what happens, cost, where) and the chat it
 *    belongs to are kept inside the row's JSON payload under `_card` and `_session` (no new column).
 *  - Yes: op decide -> the next /api/simco/turn with approval_id runs the matching *_apply_approved() once
 *    (dedupe: audit_log "Ran approval N:"). No: nothing runs; the next turn tells Grok not to retry.
 *  - Pending cards older than 24 h (from created_at) are expired and cannot be approved.
 *  - paywall-on cards are owner only: other accounts never see or decide them.
 */
const SIMKO_APPROVAL_TTL = 86400;

/** Creates a pending card and returns it (does not stop the request). */
function simko_approval_create(int $userId, string $action, string $summary, array $payload, array $card = []): array
{
    $now = time();
    $payload['_card'] = array_intersect_key($card, array_flip(['title', 'what', 'cost_usd', 'cost_unit', 'where', 'facts']));
    $payload['_session'] = (string) ($GLOBALS['simko_approval_session'] ?? '');
    $insert = simko_db()->prepare(
        'INSERT INTO approvals (user_id, action, summary, payload, status, created_at) VALUES (?, ?, ?, ?, ?, ?)'
    );
    $insert->execute([$userId, $action, simko_clip($summary, 240), json_encode($payload, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES), 'pending', $now]);
    $id = (int) simko_db()->lastInsertId();
    $row = simko_approval_row($userId, $id);
    return simko_approval_public($row ?? []);
}

function simko_guard_approval(int $userId, array $body, string $action, string $summary, array $payload, array $card = []): bool
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
    simko_ok(['approval' => simko_approval_create($userId, $action, $summary, $payload, $card)]);
}

function simko_approval_row(int $userId, int $approvalId): ?array
{
    $stmt = simko_db()->prepare('SELECT * FROM approvals WHERE id = ? AND user_id = ?');
    $stmt->execute([$approvalId, $userId]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function simko_approval_payload(array $row): array
{
    $p = json_decode((string) ($row['payload'] ?? ''), true);
    return is_array($p) ? $p : [];
}

function simko_approval_expired(array $row, ?int $now = null): bool
{
    return (string) ($row['status'] ?? '') === 'pending' && (int) ($row['created_at'] ?? 0) < ($now ?? time()) - SIMKO_APPROVAL_TTL;
}

/** Today's spend room for this account in USD: [left, cap]. */
function simko_approval_cap(int $userId): array
{
    $stmt = simko_db()->prepare('SELECT id, email FROM users WHERE id = ?');
    $stmt->execute([$userId]);
    $user = $stmt->fetch() ?: ['id' => $userId, 'email' => ''];
    $caps = simko_spend_caps();
    $cap = simko_is_grok_owner($user) ? $caps['owner'] : $caps['user'];
    $left = max(0.0, $cap - simko_spend_today($userId) / SIMKO_TICKS_PER_USD);
    $siteLeft = max(0.0, $caps['site'] - simko_spend_site_today() / SIMKO_TICKS_PER_USD);
    return [round(min($left, $siteLeft), 2), round($cap, 2)];
}

function simko_approval_money(float $usd): string
{
    return '$' . number_format($usd, $usd > 0 && $usd < 0.1 ? 3 : 2);
}

/** The "Ran approval N: ..." audit text for this card, without the prefix, or null. */
function simko_approval_result(int $userId, int $approvalId): ?string
{
    $stmt = simko_db()->prepare('SELECT summary FROM audit_log WHERE user_id = ? AND summary LIKE ? ORDER BY id LIMIT 1');
    $stmt->execute([$userId, 'Ran approval ' . $approvalId . ':%']);
    $hit = $stmt->fetchColumn();
    if (!is_string($hit)) {
        return null;
    }
    return trim(substr($hit, strlen('Ran approval ' . $approvalId . ':')));
}

/** Whether this approval already ran (any action). */
function simko_approval_already_ran(int $userId, int $approvalId): bool
{
    return simko_approval_result($userId, $approvalId) !== null;
}

/**
 * Claims the single run of an approved card: writes "Ran approval N: <label>" to audit_log inside one write
 * transaction. False when it already ran (a second Yes, a replayed turn, or two turns at once).
 */
function simko_approval_claim(int $userId, int $approvalId, string $action, string $label): bool
{
    $db = simko_db();
    $own = !$db->inTransaction();
    if ($own) {
        $db->exec('BEGIN IMMEDIATE');
    }
    try {
        if (simko_approval_already_ran($userId, $approvalId)) {
            if ($own) {
                $db->exec('COMMIT');
            }
            return false;
        }
        simko_audit($userId, $action, 'Ran approval ' . $approvalId . ': ' . $label);
        if ($own) {
            $db->exec('COMMIT');
        }
        return true;
    } catch (Throwable $e) {
        if ($own) {
            $db->exec('ROLLBACK');
        }
        throw $e;
    }
}

/** Replaces the claimed run line with the final result. */
function simko_approval_finish(int $userId, int $approvalId, string $label): void
{
    simko_db()->prepare('UPDATE audit_log SET summary = ? WHERE user_id = ? AND summary LIKE ?')
        ->execute([simko_clip('Ran approval ' . $approvalId . ': ' . $label, 240), $userId, 'Ran approval ' . $approvalId . ':%']);
}

/** The approved row for the turn's approval_id when its action is one of $actions; null otherwise. */
function simko_approval_for_apply(int $userId, array $body, array $actions): ?array
{
    $approvalId = (int) ($body['approval_id'] ?? 0);
    if ($approvalId < 1) {
        return null;
    }
    $row = simko_approval_row($userId, $approvalId);
    if (!$row || !in_array((string) $row['action'], $actions, true) || (string) $row['status'] !== 'approved') {
        return null;
    }
    return $row;
}

/** Records a short result for the card chip ("Approved, ran: ..."). */
function simko_approval_note_result(string $text): void
{
    $GLOBALS['simko_approval_result'] = simko_clip($text, 200);
}

/** Card as the chat shows it. */
function simko_approval_public(array $row): array
{
    if ($row === []) {
        return [];
    }
    $p = simko_approval_payload($row);
    $card = is_array($p['_card'] ?? null) ? $p['_card'] : [];
    $userId = (int) $row['user_id'];
    $id = (int) $row['id'];
    $status = simko_approval_expired($row) ? 'expired' : (string) $row['status'];
    $cost = isset($card['cost_usd']) && is_numeric($card['cost_usd']) ? (float) $card['cost_usd'] : 0.0;
    $unit = (string) ($card['cost_unit'] ?? '');
    [$left, $cap] = simko_approval_cap($userId);
    $costLabel = $cost > 0
        ? 'About ' . simko_approval_money($cost) . ($unit !== '' ? ' ' . $unit : '') . ' · ' . simko_approval_money($left) . ' of today\'s ' . simko_approval_money($cap) . ' left'
        : 'Free';
    $out = [
        'id' => $id,
        'action' => (string) $row['action'],
        'summary' => (string) $row['summary'],
        'status' => $status,
        'title' => (string) ($card['title'] ?? $row['summary']),
        'what' => (string) ($card['what'] ?? ''),
        'cost_usd' => $cost,
        'cost_label' => $costLabel,
        'cap_left_usd' => $left,
        'cap_usd' => $cap,
        'where' => (string) ($card['where'] ?? ''),
        'facts' => array_values(array_map('strval', is_array($card['facts'] ?? null) ? $card['facts'] : [])),
        'session_id' => (string) ($p['_session'] ?? ''),
        'created_at' => (int) $row['created_at'],
        'expires_at' => (int) $row['created_at'] + SIMKO_APPROVAL_TTL,
    ];
    if ($status === 'approved') {
        $out['result'] = simko_approval_result($userId, $id);
    }
    return $out;
}

/** Pending (and expired-but-undecided) cards for a chat, newest last. paywall-on only for the owner. */
function simko_approvals_pending(int $userId, string $sessionId, bool $isOwner): array
{
    $stmt = simko_db()->prepare('SELECT * FROM approvals WHERE user_id = ? AND status = ? ORDER BY id DESC LIMIT 50');
    $stmt->execute([$userId, 'pending']);
    $out = [];
    foreach ($stmt->fetchAll() as $row) {
        if ((string) $row['action'] === 'paywall-on' && !$isOwner) {
            continue;
        }
        $p = simko_approval_payload($row);
        $s = (string) ($p['_session'] ?? '');
        if ($s !== '' && $sessionId !== '' && $s !== $sessionId) {
            continue;
        }
        if (simko_approval_expired($row) && (int) $row['created_at'] < time() - 7 * SIMKO_APPROVAL_TTL) {
            continue; // Old expired cards are not shown again after a week.
        }
        $out[] = simko_approval_public($row);
    }
    return array_reverse($out);
}

/** Note for the system prompt about cards declined in this chat in the last 30 minutes. */
function simko_approvals_declined_note(int $userId, string $sessionId): string
{
    $stmt = simko_db()->prepare('SELECT * FROM approvals WHERE user_id = ? AND status = ? AND decided_at >= ? ORDER BY id DESC LIMIT 5');
    $stmt->execute([$userId, 'declined', time() - 1800]);
    $lines = [];
    foreach ($stmt->fetchAll() as $row) {
        $s = (string) (simko_approval_payload($row)['_session'] ?? '');
        if ($s !== '' && $s !== $sessionId) {
            continue;
        }
        $lines[] = '- ' . $row['summary'];
    }
    if ($lines === []) {
        return '';
    }
    return "The person tapped No on these, so nothing ran. Do not try them again or ask in other words unless they bring it up:\n" . implode("\n", $lines);
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
    $row = simko_approval_row($userId, $approvalId);
    if ($row && (string) $row['action'] === 'paywall-on') {
        $stmt = simko_db()->prepare('SELECT id, email FROM users WHERE id = ?');
        $stmt->execute([$userId]);
        if (!simko_is_grok_owner($stmt->fetch() ?: null)) {
            $row = null; // Only the owner may see or decide a paywall card.
        }
    }
    if (!$row || (string) $row['status'] !== 'pending') {
        simko_fail(404, 'That approval is not waiting.');
    }
    if (simko_approval_expired($row)) {
        simko_fail(410, 'Expired, ask again.', ['expired' => true, 'approval' => simko_approval_public($row)]);
    }
    // Only one decision wins, even if Yes is tapped twice at once.
    $update = simko_db()->prepare('UPDATE approvals SET status = ?, decided_at = ? WHERE id = ? AND status = ?');
    $update->execute([$decision, time(), $approvalId, 'pending']);
    if ($update->rowCount() !== 1) {
        simko_fail(404, 'That approval is not waiting.');
    }
    $verb = $decision === 'approved' ? 'Approved' : 'Declined';
    simko_audit($userId, (string) $row['action'], $verb . ': ' . $row['summary']);
    if ($decision === 'approved' && (string) $row['action'] === 'mcp-token-share') {
        // Consent is the decision itself: logged now, read tools are offered from the next turn on.
        $p = simko_approval_payload($row);
        $label = (string) ($p['server_label'] ?? ('server ' . (int) ($p['server_id'] ?? 0)));
        simko_audit($userId, 'mcp-token-consent', 'mcp-token-consent: ' . $label);
        simko_audit($userId, 'mcp-token-consent', 'Ran approval ' . $approvalId . ': ' . $label . ' read tools on');
    }
    $row = simko_approval_row($userId, $approvalId) ?? $row;
    return array_merge(simko_approval_public($row), [
        'id' => $approvalId,
        'action' => $row['action'],
        'status' => $decision,
        'summary' => $row['summary'],
    ]);
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
