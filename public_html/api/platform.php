<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';

$body = simko_require_post_json();
$user = simko_require_user();
$op = (string) ($body['op'] ?? '');
$userId = (int) $user['id'];

switch ($op) {
    case 'usage':
        if (!simko_flag('paywall')) {
            simko_fail(404, 'Usage is turned off.');
        }
        $snap = simko_usage_snapshot($userId);
        $snap['events'] = simko_usage_events($userId);
        $snap['square'] = ['connected' => simko_square_settings()['connected'], 'plan_label' => '$9 first month'];
        simko_ok($snap);
        break;
    case 'checkout':
        if (!simko_flag('paywall')) {
            simko_fail(404, 'Usage is turned off.');
        }
        $result = simko_square_checkout($userId);
        if (!empty($result['error']) && empty($result['url'])) {
            simko_fail(402, (string) $result['error'], ['connected' => !empty($result['connected'])]);
        }
        simko_ok($result);
        break;
    case 'confirm-checkout':
        if (!simko_flag('paywall')) {
            simko_fail(404, 'Usage is turned off.');
        }
        $result = simko_square_confirm($userId, trim((string) ($body['link_id'] ?? '')));
        if (empty($result['paid'])) {
            simko_fail(402, (string) ($result['error'] ?? 'Nothing was charged.'));
        }
        simko_ok(simko_usage_snapshot($userId));
        break;
    case 'start-trial':
        if (!simko_flag('paywall')) {
            simko_fail(404, 'Usage is turned off.');
        }
        simko_ok(simko_usage_start_trial($userId));
        break;
    default:
        simko_fail(400, 'That platform step is not recognized.');
}
