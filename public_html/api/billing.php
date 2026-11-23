<?php
declare(strict_types=1);

/*
 * Picture billing for paid subscribers. Two modes behind one switch:
 *   billing.image_billing_mode (or env IMAGE_BILLING_MODE) = 'invoice' (default) | 'metered'
 *
 * invoice: charges stay 'pending' in image_charges during the month. A monthly run
 *          (api/image-billing-run.php, CLI only) puts each subscriber's pending total on one
 *          Stripe invoice: POST /v1/invoices, POST /v1/invoiceitems, POST /v1/invoices/{id}/finalize.
 *          Totals under billing.image_invoice_min_cents (default 50, Stripe's US minimum) roll over.
 * metered: each picture sends one Stripe billing meter event right away
 *          (POST /v1/billing/meter_events, https://docs.stripe.com/api/billing/meter-event/create),
 *          value = the picture's cost in whole cents, rounded up. The $9.99 checkout then also adds
 *          stripe.metered_price_id (a per-unit $0.01 price on that meter) so Stripe bills the usage
 *          on the monthly subscription invoice.
 *
 * Nothing is sent to Stripe unless the paywall flag is on and Stripe is connected (key + price id).
 * The owner is never billed (status owner_not_billed is never picked up here).
 */

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/stripe.php';

function simko_image_billing_mode(): string
{
    $env = getenv('IMAGE_BILLING_MODE');
    $raw = is_string($env) && trim($env) !== ''
        ? $env
        : (string) (simko_config_or_empty()['billing']['image_billing_mode'] ?? 'invoice');
    return strtolower(trim($raw)) === 'metered' ? 'metered' : 'invoice';
}

function simko_image_billing_settings(): array
{
    $cfg = simko_config_or_empty();
    $stripe = is_array($cfg['stripe'] ?? null) ? $cfg['stripe'] : [];
    $billing = is_array($cfg['billing'] ?? null) ? $cfg['billing'] : [];
    $meter = simko_config_secret($stripe, 'meter_event_name', 'STRIPE_METER_EVENT_NAME');
    $metered = simko_config_secret($stripe, 'metered_price_id', 'STRIPE_METERED_PRICE_ID');
    if (!simko_secret_is_usable($metered)) {
        $metered = '';
    }
    $min = (int) ($billing['image_invoice_min_cents'] ?? 50);
    $mode = simko_image_billing_mode();
    $stripeOn = simko_stripe_settings()['connected'];
    return [
        'mode' => $mode,
        'meter_event_name' => $meter !== '' ? $meter : 'simko_picture_cents',
        'metered_price_id' => $metered,
        'invoice_min_cents' => max(0, $min),
        // Live billing only when the paywall is on and Stripe is connected.
        'active' => simko_flag('paywall') && $stripeOn,
        'ready' => $stripeOn && ($mode === 'invoice' || $metered !== ''),
    ];
}

function simko_ticks_cents(int $ticks): int
{
    return $ticks <= 0 ? 0 : intdiv($ticks + 99999999, 100000000);
}

function simko_image_billing_mark(int $chargeId, int $userId, string $mode, string $state, string $ref = '', string $error = ''): void
{
    $stmt = simko_db()->prepare(
        'INSERT INTO image_billing (charge_id, user_id, mode, stripe_ref, state, error, attempts, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, 1, ?)
         ON CONFLICT(charge_id) DO UPDATE SET mode = excluded.mode, stripe_ref = excluded.stripe_ref,
            state = excluded.state, error = excluded.error, attempts = image_billing.attempts + 1,
            updated_at = excluded.updated_at'
    );
    $stmt->execute([$chargeId, $userId, $mode, $ref, $state, simko_clip($error, 240), time()]);
}

function simko_stripe_error_text(array $result): string
{
    $data = json_decode((string) $result['body'], true);
    $msg = is_array($data) ? (string) ($data['error']['message'] ?? '') : '';
    return 'HTTP ' . $result['code'] . ($msg !== '' ? ': ' . $msg : ($result['error'] !== '' ? ': ' . $result['error'] : ''));
}

/** Metered mode: send one meter event for one pending picture charge. Returns the new status. */
function simko_image_meter_charge(int $chargeId): array
{
    $settings = simko_image_billing_settings();
    $stmt = simko_db()->prepare('SELECT id, user_id, cost_ticks, status, created_at FROM image_charges WHERE id = ?');
    $stmt->execute([$chargeId]);
    $row = $stmt->fetch();
    if (!$row || (string) $row['status'] !== 'pending') {
        return ['sent' => false, 'reason' => 'not pending'];
    }
    if (!$settings['active'] || $settings['mode'] !== 'metered') {
        return ['sent' => false, 'reason' => 'metered billing is off'];
    }
    $userId = (int) $row['user_id'];
    $customer = (string) (simko_subscription($userId)['stripe_customer_id'] ?? '');
    if ($customer === '') {
        simko_image_billing_mark($chargeId, $userId, 'metered', 'failed', '', 'no Stripe customer on this account');
        return ['sent' => false, 'reason' => 'no Stripe customer'];
    }
    $identifier = 'simko-pic-' . $chargeId;
    $result = simko_stripe_request('/v1/billing/meter_events', [
        'event_name' => $settings['meter_event_name'],
        'payload' => [
            'stripe_customer_id' => $customer,
            'value' => (string) simko_ticks_cents((int) $row['cost_ticks']),
        ],
        'identifier' => $identifier,
        // Stripe accepts timestamps up to 35 days back.
        'timestamp' => (string) max((int) $row['created_at'], time() - 34 * 86400),
    ], $identifier);
    if ($result['code'] < 200 || $result['code'] >= 300) {
        simko_image_billing_mark($chargeId, $userId, 'metered', 'failed', '', simko_stripe_error_text($result));
        return ['sent' => false, 'reason' => 'Stripe refused the meter event'];
    }
    simko_db()->prepare("UPDATE image_charges SET status = 'metered' WHERE id = ? AND status = 'pending'")->execute([$chargeId]);
    simko_image_billing_mark($chargeId, $userId, 'metered', 'reported', $identifier);
    return ['sent' => true, 'identifier' => $identifier];
}

/** Called right after a subscriber's picture is recorded. Never fails the picture. */
function simko_image_billing_after_charge(int $chargeId): array
{
    try {
        if (simko_image_billing_mode() !== 'metered') {
            return ['mode' => 'invoice', 'sent' => false, 'reason' => 'added to the monthly picture invoice'];
        }
        return ['mode' => 'metered'] + simko_image_meter_charge($chargeId);
    } catch (Throwable $e) {
        return ['mode' => simko_image_billing_mode(), 'sent' => false, 'reason' => 'billing will retry'];
    }
}

/** First second (UTC) of the month after $period (YYYY-MM). */
function simko_period_end(string $period): int
{
    if (!preg_match('/^(\d{4})-(\d{2})$/', $period, $m)) {
        throw new InvalidArgumentException('period must be YYYY-MM');
    }
    $y = (int) $m[1];
    $mo = (int) $m[2] + 1;
    if ($mo === 13) {
        $mo = 1;
        $y++;
    }
    return gmmktime(0, 0, 0, $mo, 1, $y);
}

function simko_previous_period(?int $now = null): string
{
    $now = $now ?? time();
    return gmdate('Y-m', gmmktime(0, 0, 0, (int) gmdate('n', $now) - 1, 1, (int) gmdate('Y', $now)));
}

/**
 * Invoice mode: one Stripe invoice per subscriber for every pending picture charge made before the
 * end of $period. $dryRun reports what would be billed and sends nothing.
 */
function simko_image_invoice_run(?string $period = null, bool $dryRun = false): array
{
    $settings = simko_image_billing_settings();
    $period = $period ?? simko_previous_period();
    $end = simko_period_end($period);
    $out = ['period' => $period, 'mode' => $settings['mode'], 'dry_run' => $dryRun, 'active' => $settings['active'], 'users' => []];
    if ($settings['mode'] !== 'invoice') {
        $out['skipped'] = 'image_billing_mode is metered';
        return $out;
    }
    $stmt = simko_db()->prepare(
        "SELECT user_id, COUNT(*) AS n, SUM(cost_ticks) AS ticks, GROUP_CONCAT(id) AS ids FROM image_charges
         WHERE status = 'pending' AND created_at < ? GROUP BY user_id ORDER BY user_id"
    );
    $stmt->execute([$end]);
    foreach ($stmt->fetchAll() as $row) {
        $userId = (int) $row['user_id'];
        $ids = array_map('intval', explode(',', (string) $row['ids']));
        $cents = simko_ticks_cents((int) $row['ticks']);
        $line = ['user_id' => $userId, 'pictures' => (int) $row['n'], 'cents' => $cents, 'state' => ''];
        if ($cents < $settings['invoice_min_cents']) {
            $line['state'] = 'rolled_over_below_minimum';
            $out['users'][] = $line;
            continue;
        }
        if ($dryRun || !$settings['active']) {
            $line['state'] = $dryRun ? 'would_invoice' : 'billing_inactive';
            $out['users'][] = $line;
            continue;
        }
        $customer = (string) (simko_subscription($userId)['stripe_customer_id'] ?? '');
        if ($customer === '') {
            $line['state'] = 'no_stripe_customer';
            $out['users'][] = $line;
            continue;
        }
        $key = 'simko-pic-invoice-' . $userId . '-' . $period . '-' . substr(sha1(implode(',', $ids)), 0, 10);
        $label = $row['n'] . ' Simko SI picture' . ((int) $row['n'] === 1 ? '' : 's') . ' through ' . $period;
        $inv = simko_stripe_request('/v1/invoices', [
            'customer' => $customer,
            'collection_method' => 'charge_automatically',
            'auto_advance' => 'true',
            'pending_invoice_items_behavior' => 'exclude',
            'description' => $label,
            'metadata' => ['simko_kind' => 'pictures', 'user_id' => (string) $userId, 'period' => $period],
        ], $key . '-inv');
        $invData = json_decode((string) $inv['body'], true);
        $invoiceId = is_array($invData) ? (string) ($invData['id'] ?? '') : '';
        if ($inv['code'] >= 300 || $invoiceId === '') {
            $line['state'] = 'failed';
            $line['error'] = simko_stripe_error_text($inv);
            $out['users'][] = $line;
            continue;
        }
        $item = simko_stripe_request('/v1/invoiceitems', [
            'customer' => $customer,
            'invoice' => $invoiceId,
            'amount' => (string) $cents,
            'currency' => 'usd',
            'description' => $label,
            'metadata' => ['simko_kind' => 'pictures', 'charge_ids' => simko_clip(implode(',', $ids), 480)],
        ], $key . '-item');
        if ($item['code'] >= 300) {
            $line['state'] = 'failed';
            $line['error'] = simko_stripe_error_text($item);
            $out['users'][] = $line;
            continue;
        }
        $fin = simko_stripe_request('/v1/invoices/' . rawurlencode($invoiceId) . '/finalize', ['auto_advance' => 'true'], $key . '-fin');
        if ($fin['code'] >= 300) {
            $line['state'] = 'failed';
            $line['error'] = simko_stripe_error_text($fin);
            $out['users'][] = $line;
            continue;
        }
        $db = simko_db();
        $db->beginTransaction();
        $upd = $db->prepare("UPDATE image_charges SET status = 'invoiced' WHERE id = ? AND status = 'pending'");
        foreach ($ids as $id) {
            $upd->execute([$id]);
            simko_image_billing_mark($id, $userId, 'invoice', 'invoiced', $invoiceId);
        }
        $db->commit();
        $line['state'] = 'invoiced';
        $line['invoice_id'] = $invoiceId;
        $out['users'][] = $line;
    }
    return $out;
}

/** Metered mode: retry meter events that failed or were made while billing was briefly unreachable. */
function simko_image_meter_retry(int $limit = 200): array
{
    $settings = simko_image_billing_settings();
    $out = ['mode' => $settings['mode'], 'active' => $settings['active'], 'sent' => 0, 'failed' => 0];
    if ($settings['mode'] !== 'metered' || !$settings['active']) {
        return $out;
    }
    $stmt = simko_db()->prepare(
        "SELECT id FROM image_charges WHERE status = 'pending' AND created_at > ? ORDER BY id LIMIT " . max(1, $limit)
    );
    $stmt->execute([time() - 34 * 86400]);
    foreach ($stmt->fetchAll(PDO::FETCH_COLUMN) as $id) {
        $r = simko_image_meter_charge((int) $id);
        $r['sent'] ? $out['sent']++ : $out['failed']++;
    }
    return $out;
}

/** Webhook: a picture invoice was paid. */
function simko_image_invoice_paid(array $invoice): int
{
    if ((string) ($invoice['metadata']['simko_kind'] ?? '') !== 'pictures') {
        return 0;
    }
    $invoiceId = (string) ($invoice['id'] ?? '');
    if ($invoiceId === '') {
        return 0;
    }
    $stmt = simko_db()->prepare(
        "UPDATE image_charges SET status = 'paid' WHERE status = 'invoiced'
           AND id IN (SELECT charge_id FROM image_billing WHERE stripe_ref = ?)"
    );
    $stmt->execute([$invoiceId]);
    simko_db()->prepare("UPDATE image_billing SET state = 'paid', updated_at = ? WHERE stripe_ref = ?")->execute([time(), $invoiceId]);
    return $stmt->rowCount();
}
