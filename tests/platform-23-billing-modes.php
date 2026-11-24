<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Picture billing modes (invoice | metered) and the paywall gate, against mocked xAI and mocked Stripe.
// No real Stripe or xAI call is made.
$base = 21000 + (getmypid() % 15000);
$mockPort = $base + 1;
$sitePort = $base + 2;
$stripePort = $base + 3;
$capture = sys_get_temp_dir() . '/simko-bm-capture-' . getmypid() . '.json';
$journal = sys_get_temp_dir() . '/simko-bm-stripe-' . getmypid() . '.log';
$failFile = sys_get_temp_dir() . '/simko-bm-fail-' . getmypid() . '.txt';
@unlink($capture);
@unlink($journal);
@unlink($failFile);
putenv('SIMKO_STRIPE_LOG=' . $journal);
putenv('SIMKO_STRIPE_FAIL=' . $failFile);
putenv('IMAGE_BILLING_MODE');

[$mock, $mockPipes] = platform_mock($mockPort);
[$stripe, $stripePipes] = platform_stripe_mock($stripePort, $capture);
@unlink($journal);

$ownerEmail = 'bm-owner-' . getmypid() . '@simkosi.test';
$webhookSecret = 'whsec_test_local_only';
$writeConfig = static function (string $mode, bool $paywall) use (&$private, $mockPort, $stripePort, $ownerEmail, $webhookSecret): string {
    $dir = platform_private('billmodes', ['paywall' => $paywall, 'images' => true], [
        'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
        'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
        'grok_access' => 'owner', // these checks cover the owner-lock mode
        'billing' => ['provider' => 'stripe', 'image_billing_mode' => $mode, 'image_invoice_min_cents' => 10],
        'stripe' => [
            'restricted_key' => 'rk_test_local_mock',
            'secret_key' => '',
            'webhook_secret' => $webhookSecret,
            'price_id' => 'price_test_999_monthly',
            'metered_price_id' => 'price_test_picture_cent',
            'meter_event_name' => 'simko_picture_cents',
            'api_base' => 'http://127.0.0.1:' . $stripePort,
            'api_version' => '2026-09-30.endive',
        ],
    ]);
    // PHP's opcache rechecks config.php every couple of seconds; wait so the new mode is read.
    sleep(3);
    return $dir;
};
$private = $writeConfig('invoice', true);
[$site, $sitePipes] = platform_site($private, $sitePort);

$stripeCalls = static function (?string $path = null) use ($journal): array {
    if (!is_file($journal)) {
        return [];
    }
    $out = [];
    foreach (array_filter(explode("\n", (string) file_get_contents($journal))) as $line) {
        $row = json_decode($line, true);
        if (is_array($row) && ($path === null || $row['path'] === $path)) {
            $out[] = $row;
        }
    }
    return $out;
};
$runCli = static function (array $args) use (&$private): array {
    $cmd = 'SIMKOSI_PRIVATE=' . escapeshellarg($private) . ' php '
        . escapeshellarg($GLOBALS['simko_root'] . '/public_html/api/image-billing-run.php') . ' ' . implode(' ', array_map('escapeshellarg', $args));
    $out = shell_exec($cmd . ' 2>&1');
    $data = json_decode((string) $out, true);
    platform_assert(is_array($data), 'billing run prints JSON: ' . substr((string) $out, 0, 300));
    return $data;
};

$owner = platform_signup($sitePort, $ownerEmail);
$sub = platform_signup($sitePort, 'bm-sub-' . getmypid() . '@simkosi.test');
$small = platform_signup($sitePort, 'bm-small-' . getmypid() . '@simkosi.test');
$nocus = platform_signup($sitePort, 'bm-nocus-' . getmypid() . '@simkosi.test');
$free = platform_signup($sitePort, 'bm-free-' . getmypid() . '@simkosi.test');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite', null, null, [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$db->exec('PRAGMA busy_timeout = 3000');
$idOf = static function (string $prefix) use ($db): int {
    return (int) $db->query("SELECT id FROM users WHERE email LIKE '" . $prefix . "%'")->fetchColumn();
};
$subId = $idOf('bm-sub-');
$smallId = $idOf('bm-small-');
$nocusId = $idOf('bm-nocus-');
// What the Stripe webhook writes after checkout (customer ids are mock values).
$ins = $db->prepare("INSERT INTO subscriptions (user_id, status, trial_until, stripe_customer_id, stripe_subscription_id, updated_at) VALUES (?, 'paid', 0, ?, ?, ?)");
$ins->execute([$subId, 'cus_test_sub', 'sub_test_sub', time()]);
$ins->execute([$smallId, 'cus_test_small', 'sub_test_small', time()]);
$ins->execute([$nocusId, '', '', time()]);
$status = static function (int $userId) use ($db): array {
    $st = $db->prepare('SELECT status FROM image_charges WHERE user_id = ? ORDER BY id');
    $st->execute([$userId]);
    return $st->fetchAll(PDO::FETCH_COLUMN);
};

// ---------- A. invoice mode (default), paywall on ----------
$u = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $sub['token']);
platform_assert(($u['data']['billing']['image_billing_mode'] ?? '') === 'invoice' && !empty($u['data']['billing']['image_billing_ready']), 'usage reports invoice mode, ready');
$co = platform_api($sitePort, '/api/platform', ['op' => 'checkout'], $sub['token']);
platform_assert($co['status'] === 200, 'checkout opens in invoice mode');
$fields = json_decode((string) file_get_contents($capture), true)['fields'] ?? [];
platform_assert(count($fields['line_items'] ?? []) === 1 && $fields['line_items'][0]['price'] === 'price_test_999_monthly', 'invoice mode checkout has only the $9.99 price');

for ($i = 1; $i <= 3; $i++) {
    $p = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'invoice picture ' . $i], $sub['token']);
    platform_assert($p['status'] === 200 && $p['data']['image']['charge_status'] === 'pending' && ($p['data']['image']['billing']['mode'] ?? '') === 'invoice', 'invoice mode picture ' . $i . ' stays pending for the monthly invoice');
}
$sp = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'one small picture'], $small['token']);
platform_assert($sp['status'] === 200, 'second subscriber picture');
$op = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'owner picture'], $owner['token']);
platform_assert($op['data']['image']['charge_status'] === 'owner_not_billed' && $op['data']['image']['billing'] === null, 'owner picture is never billed');
platform_assert($stripeCalls('/v1/billing/meter_events') === [], 'invoice mode sends no meter events');
platform_assert($stripeCalls('/v1/invoices') === [], 'no invoice before the monthly run');

// Move this month's charges into last month, then run the monthly job.
$db->exec('UPDATE image_charges SET created_at = created_at - 40 * 86400');
$lastMonth = gmdate('Y-m', gmmktime(0, 0, 0, (int) gmdate('n') - 1, 1, (int) gmdate('Y')));
$dry = $runCli(['--dry-run']);
$byUser = [];
foreach ($dry['users'] as $line) {
    $byUser[$line['user_id']] = $line;
}
platform_assert(($dry['period'] ?? '') === $lastMonth && !empty($dry['dry_run']), 'dry run bills last month');
platform_assert(($byUser[$subId]['state'] ?? '') === 'would_invoice' && $byUser[$subId]['cents'] === 12 && $byUser[$subId]['pictures'] === 3, 'dry run: 3 pictures = 12 cents for the subscriber');
platform_assert(($byUser[$smallId]['state'] ?? '') === 'rolled_over_below_minimum', 'totals under the minimum roll over');
platform_assert(!isset($byUser[$idOf('bm-owner-')]), 'the owner is not on the invoice run');
platform_assert($stripeCalls() === [] || $stripeCalls('/v1/invoices') === [], 'dry run sends nothing to Stripe');

$run = $runCli([]);
$byUser = [];
foreach ($run['users'] as $line) {
    $byUser[$line['user_id']] = $line;
}
$invoiceId = (string) ($byUser[$subId]['invoice_id'] ?? '');
platform_assert(($byUser[$subId]['state'] ?? '') === 'invoiced' && $invoiceId !== '', 'monthly run invoices the subscriber');
$invCreate = $stripeCalls('/v1/invoices');
$items = $stripeCalls('/v1/invoiceitems');
$fin = $stripeCalls('/v1/invoices/' . $invoiceId . '/finalize');
platform_assert(count($invCreate) === 1 && $invCreate[0]['fields']['customer'] === 'cus_test_sub' && $invCreate[0]['fields']['metadata']['simko_kind'] === 'pictures', 'one picture invoice for the subscriber customer');
platform_assert(($invCreate[0]['fields']['pending_invoice_items_behavior'] ?? '') === 'exclude' && ($invCreate[0]['fields']['collection_method'] ?? '') === 'charge_automatically', 'invoice charges the card on file and only holds the picture item');
platform_assert(count($items) === 1 && $items[0]['fields']['amount'] === '12' && $items[0]['fields']['currency'] === 'usd' && $items[0]['fields']['invoice'] === $invoiceId, 'one invoice item of 12 cents usd');
platform_assert(count($fin) === 1, 'invoice is finalized');
platform_assert($invCreate[0]['idempotency_key'] !== '' && str_starts_with($invCreate[0]['idempotency_key'], 'simko-pic-invoice-' . $subId . '-' . $lastMonth), 'invoice uses an idempotency key per user and month');
platform_assert(str_contains($invCreate[0]['authorization'], 'rk_test_local_mock'), 'invoice uses the configured key');
platform_assert($status($subId) === ['invoiced', 'invoiced', 'invoiced'], 'charges are marked invoiced');
platform_assert($status($smallId) === ['pending'], 'the small total stays pending');
$again = $runCli([]);
platform_assert(count($stripeCalls('/v1/invoices')) === 1, 'running again does not invoice twice');

$paidEvt = json_encode(['id' => 'evt_inv_paid_1', 'object' => 'event', 'type' => 'invoice.paid', 'data' => ['object' => [
    'id' => $invoiceId, 'object' => 'invoice', 'customer' => 'cus_test_sub', 'metadata' => ['simko_kind' => 'pictures', 'user_id' => (string) $subId],
]]], JSON_UNESCAPED_SLASHES);
$wh = platform_post_raw($sitePort, '/api/stripe-webhook', $paidEvt, ['Stripe-Signature' => platform_stripe_sign($paidEvt, $webhookSecret)]);
platform_assert($wh['status'] === 200, 'signed invoice.paid webhook is accepted');
platform_assert($status($subId) === ['paid', 'paid', 'paid'], 'invoice.paid marks the picture charges paid');
$badWh = platform_post_raw($sitePort, '/api/stripe-webhook', $paidEvt, ['Stripe-Signature' => platform_stripe_sign($paidEvt, 'whsec_wrong')]);
platform_assert($badWh['status'] === 400, 'a webhook signed with the wrong secret is rejected');
$subRow = $db->query('SELECT status FROM subscriptions WHERE user_id = ' . $subId)->fetchColumn();
platform_assert($subRow === 'paid', 'the plan stays paid');

// ---------- B. metered mode ----------
platform_stop($site, $sitePipes);
$writeConfigMetered = $writeConfig('metered', true);
platform_assert($writeConfigMetered === $private, 'same private dir for metered mode');
[$site, $sitePipes] = platform_site($private, $sitePort);
$u = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $sub['token']);
platform_assert(($u['data']['billing']['image_billing_mode'] ?? '') === 'metered' && !empty($u['data']['billing']['image_billing_ready']), 'usage reports metered mode, ready ' . json_encode($u));
$co = platform_api($sitePort, '/api/platform', ['op' => 'checkout'], $sub['token']);
$fields = json_decode((string) file_get_contents($capture), true)['fields'] ?? [];
platform_assert($co['status'] === 200 && count($fields['line_items'] ?? []) === 2, 'metered checkout has two line items');
platform_assert($fields['line_items'][1]['price'] === 'price_test_picture_cent' && !isset($fields['line_items'][1]['quantity']), 'metered price is added with no quantity');

$m1 = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'metered picture'], $sub['token']);
platform_assert($m1['status'] === 200 && $m1['data']['image']['charge_status'] === 'metered' && !empty($m1['data']['image']['billing']['sent']), 'metered picture is reported right away');
platform_assert(($m1['data']['ledger']['billing_mode'] ?? '') === 'metered' && ($m1['data']['ledger']['month_billed_count'] ?? 0) >= 1 && $m1['data']['ledger']['month_pending_count'] === 0, 'the ledger shows metered pictures as billed this month');
$events = $stripeCalls('/v1/billing/meter_events');
platform_assert(count($events) === 1, 'one meter event per picture');
$ev = $events[0];
platform_assert($ev['fields']['event_name'] === 'simko_picture_cents' && $ev['fields']['payload']['stripe_customer_id'] === 'cus_test_sub' && $ev['fields']['payload']['value'] === '4', 'meter event: 4 cents to the subscriber customer');
platform_assert(str_starts_with($ev['fields']['identifier'], 'simko-pic-') && $ev['idempotency_key'] === $ev['fields']['identifier'], 'meter event has a stable identifier and idempotency key');

file_put_contents($failFile, '/v1/billing/meter_events');
$m2 = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'metered while stripe is down'], $sub['token']);
platform_assert($m2['status'] === 200 && $m2['data']['image']['charge_status'] === 'pending' && empty($m2['data']['image']['billing']['sent']), 'a Stripe outage does not lose the picture; the charge stays pending');
$failedRow = $db->query("SELECT state, error FROM image_billing WHERE state = 'failed'")->fetch(PDO::FETCH_ASSOC);
platform_assert(is_array($failedRow) && str_contains($failedRow['error'], '500'), 'the failure is recorded');
@unlink($failFile);
$retry = $runCli([]);
platform_assert(($retry['retry']['sent'] ?? 0) === 1, 'the billing run retries the meter event');
$last = $status($subId);
platform_assert(end($last) === 'metered', 'retried charge is now metered');
$nc = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'no customer yet'], $nocus['token']);
platform_assert($nc['status'] === 200 && $nc['data']['image']['charge_status'] === 'pending', 'a subscriber with no Stripe customer keeps the picture, charge pending');
$inv = $runCli(['--dry-run']);
platform_assert(($inv['mode'] ?? '') === 'metered', 'metered mode run does not invoice');
platform_assert(count($stripeCalls('/v1/invoices')) === 1, 'no invoices in metered mode');

// ---------- C. paywall off: nothing changes for users, nothing goes to Stripe ----------
platform_stop($site, $sitePipes);
$writeConfig('metered', false);
[$site, $sitePipes] = platform_site($private, $sitePort);
$before = count($stripeCalls());
$off = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'paywall off picture'], $sub['token']);
platform_assert($off['status'] === 200 && $off['data']['image']['charge_status'] === 'pending', 'paywall off: subscriber picture is recorded, not sent');
platform_assert(count($stripeCalls()) === $before, 'paywall off: no Stripe call');
platform_assert(platform_api($sitePort, '/api/platform', ['op' => 'checkout'], $sub['token'])['status'] === 404, 'paywall off: checkout is closed');
platform_assert(platform_api($sitePort, '/api/platform', ['op' => 'usage'], $sub['token'])['status'] === 404, 'paywall off: usage is hidden');
$f = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'free try'], $free['token']);
platform_assert($f['status'] === 402, 'paywall off: free accounts still cannot make pictures');
$writeConfig('invoice', false);
$idle = $runCli([]);
foreach ($idle['users'] as $line) {
    platform_assert(in_array($line['state'], ['billing_inactive', 'rolled_over_below_minimum'], true), 'paywall off: the monthly run sends nothing (' . $line['state'] . ')');
}
platform_assert(count($stripeCalls()) === $before, 'paywall off: still no Stripe call after the run');
$web = @file_get_contents('http://127.0.0.1:' . $sitePort . '/api/image-billing-run.php', false, stream_context_create(['http' => ['ignore_errors' => true]]));
platform_assert(isset($http_response_header[0]) && str_contains($http_response_header[0], '404'), 'the billing run is not reachable from the web');

platform_stop($site, $sitePipes);
platform_stop($stripe, $stripePipes);
platform_stop($mock, $mockPipes);
@unlink($capture);
@unlink($journal);
fwrite(STDOUT, "billing mode tests passed\n");
