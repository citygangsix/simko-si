<?php
declare(strict_types=1);

/*
 * Monthly picture billing run. Command line only (cron); the web gets a 404.
 *   php image-billing-run.php                 invoice mode: bill last month's pending pictures
 *   php image-billing-run.php --period=2026-11
 *   php image-billing-run.php --dry-run       report only, nothing sent to Stripe
 * In metered mode the same command retries meter events that did not go through.
 */
if (PHP_SAPI !== 'cli') {
    http_response_code(404);
    exit;
}

require_once __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/billing.php';

$opts = getopt('', ['period:', 'dry-run']);
$period = isset($opts['period']) && is_string($opts['period']) ? $opts['period'] : null;
$dry = array_key_exists('dry-run', $opts);
$result = simko_image_billing_mode() === 'metered'
    ? ['mode' => 'metered', 'retry' => $dry ? 'skipped (dry run)' : simko_image_meter_retry()]
    : simko_image_invoice_run($period, $dry);
echo json_encode($result, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES), "\n";
