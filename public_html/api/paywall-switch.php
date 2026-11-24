<?php
declare(strict_types=1);

/*
 * Owner-only "turn the paywall on" Yes/No card (action paywall-on).
 *  - Only an owner account can ask for it, see it, or decide it.
 *  - Card: price, free messages, Stripe mode (test/live) and account last 4 only, who is affected.
 *  - Yes sets the paywall flag in site_settings ('flag_paywall'); simko_flag reads that first, config second.
 *  - Turning it off again needs no card. Nothing here calls Stripe.
 */

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/approvals.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/stripe.php';

/** Stripe mode from the configured key prefix (never calls Stripe): ['mode' => test|live|none, 'last4' => '1234'|'']. */
function simko_paywall_stripe_mode(): array
{
    $raw = simko_config_or_empty()['stripe'] ?? [];
    $raw = is_array($raw) ? $raw : [];
    $key = simko_stripe_settings()['secret_key'];
    $mode = 'none';
    if (preg_match('/^(sk|rk)_test_/', $key)) {
        $mode = 'test';
    } elseif (preg_match('/^(sk|rk)_live_/', $key)) {
        $mode = 'live';
    }
    $account = trim((string) ($raw['account_id'] ?? ''));
    $source = $account !== '' ? $account : $key;
    return ['mode' => $mode, 'last4' => $source !== '' ? substr($source, -4) : ''];
}

/** Accounts the paywall would apply to: everyone but the owner accounts. */
function simko_paywall_affected_count(): int
{
    $n = 0;
    foreach (simko_db()->query('SELECT id, email FROM users')->fetchAll() as $u) {
        if (!simko_is_grok_owner($u)) {
            $n++;
        }
    }
    return $n;
}

function simko_paywall_price_label(): string
{
    $raw = simko_config_or_empty()['billing'] ?? [];
    $label = is_array($raw) ? trim((string) ($raw['price_label'] ?? '')) : '';
    return $label !== '' ? $label : simko_plan_label();
}

function simko_paywall_card_facts(): array
{
    $stripe = simko_paywall_stripe_mode();
    $price = simko_paywall_price_label();
    $free = simko_usage_free_limit();
    $affected = simko_paywall_affected_count();
    $stripeText = $stripe['mode'] === 'none' ? 'not connected' : $stripe['mode'] . ' mode' . ($stripe['last4'] !== '' ? ', account ending ' . $stripe['last4'] : '');
    return [
        'title' => 'Turn the paywall on',
        'what' => 'After ' . $free . ' free messages, people need the paid plan at ' . $price . ' to keep chatting. You can turn it off again any time.'
            . ($stripe['mode'] === 'live' ? ' Stripe is in live mode: real charges still need your own OK in chat first.' : ''),
        'cost_usd' => 0,
        'where' => 'Price ' . $price . ' · ' . $free . ' free messages · Stripe ' . $stripeText . ' · affects ' . $affected . ' non-owner account' . ($affected === 1 ? '' : 's'),
        'facts' => ['Price: ' . $price, 'Free messages: ' . $free, 'Stripe: ' . $stripeText, 'Who: ' . $affected . ' non-owner account' . ($affected === 1 ? '' : 's') . ' (owners are never limited)'],
    ];
}

/** Owner asks to turn the paywall on: returns the pending card (does not stop the request). */
function simko_paywall_request_on(array $user): array
{
    simko_require_grok_owner($user);
    if (!simko_flag('approvals')) {
        simko_fail(403, 'Turning the paywall on needs the in-chat Yes card, and approvals are turned off.', ['approvals_off' => true]);
    }
    if (simko_flag('paywall')) {
        simko_fail(409, 'The paywall is already on.');
    }
    $facts = simko_paywall_card_facts();
    return simko_approval_create((int) $user['id'], 'paywall-on', 'Turn the paywall on (' . simko_paywall_price_label() . ', ' . simko_usage_free_limit() . ' free messages)', [
        'price' => simko_paywall_price_label(),
        'free' => simko_usage_free_limit(),
        'stripe_mode' => simko_paywall_stripe_mode()['mode'],
    ], $facts);
}

/** Runs an approved paywall-on once. Re-checks the owner. */
function simko_paywall_apply_approval(int $userId, array $row): array
{
    $stmt = simko_db()->prepare('SELECT id, email FROM users WHERE id = ?');
    $stmt->execute([$userId]);
    if (!simko_is_grok_owner($stmt->fetch() ?: null)) {
        return ['ok' => false, 'note' => 'Only the owner can turn the paywall on, so nothing changed.'];
    }
    $approvalId = (int) $row['id'];
    if (!simko_approval_claim($userId, $approvalId, 'paywall-ran', 'Paywall on')) {
        return ['ok' => false, 'note' => 'The paywall was already turned on from that card.', 'already' => true];
    }
    simko_flag_store('paywall', true);
    $label = 'Paywall on: ' . simko_paywall_price_label() . ' after ' . simko_usage_free_limit() . ' free messages (Stripe ' . simko_paywall_stripe_mode()['mode'] . ')';
    simko_approval_finish($userId, $approvalId, $label);
    simko_approval_note_result($label);
    return ['ok' => true, 'note' => $label, 'paywall' => true];
}

/** chat.php: on the turn after Yes. */
function simko_paywall_apply_approved(int $userId, array $body): string
{
    $row = simko_approval_for_apply($userId, $body, ['paywall-on']);
    if (!$row) {
        return '';
    }
    $res = simko_paywall_apply_approval($userId, $row);
    return 'Paywall result: ' . $res['note'] . '. Tell the owner in one line. Do not ask again.';
}

/** Owner turns the paywall off (no card needed). */
function simko_paywall_off(array $user): void
{
    simko_require_grok_owner($user);
    simko_flag_store('paywall', false);
    simko_audit((int) $user['id'], 'paywall-off', 'Paywall turned off');
}
