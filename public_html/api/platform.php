<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/approvals.php';
require_once __DIR__ . '/recall.php';
require_once __DIR__ . '/routines.php';
require_once __DIR__ . '/images.php';

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
        simko_guard_approval($userId, $body, 'spend', 'Pay $9 for the first month of Simko SI', ['op' => 'checkout']);
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
    case 'decide':
        if (!simko_flag('approvals')) {
            simko_fail(404, 'Approvals are turned off.');
        }
        $decision = (string) ($body['decision'] ?? '');
        $decided = simko_decide_approval($userId, (int) ($body['approval_id'] ?? 0), $decision === 'approve' ? 'approved' : 'declined');
        simko_ok(['approval' => $decided, 'audit' => simko_audit_rows($userId)]);
        break;
    case 'audit':
        if (!simko_flag('approvals')) {
            simko_fail(404, 'Approvals are turned off.');
        }
        simko_ok(['audit' => simko_audit_rows($userId)]);
        break;
    case 'imagine':
        if (!simko_flag('images')) {
            simko_fail(404, 'Pictures are turned off.');
        }
        $childId = simko_requested_child($userId, $body);
        $image = simko_image_generate($userId, (string) ($body['prompt'] ?? ''), $childId);
        simko_ok(['image' => $image, 'images' => simko_image_rows($userId)]);
        break;
    case 'images':
        if (!simko_flag('images')) {
            simko_fail(404, 'Pictures are turned off.');
        }
        simko_ok([
            'images' => simko_image_rows($userId),
            'video' => 'Video is not made here. Video stays on a rented GPU, on the desktop app Wan path.',
        ]);
        break;
    case 'routines':
        if (!simko_flag('routines')) {
            simko_fail(404, 'Routines are turned off.');
        }
        simko_ok([
            'routines' => simko_routine_rows($userId),
            'deliveries' => simko_routine_deliveries($userId),
            'kinds' => simko_routine_kinds(),
        ]);
        break;
    case 'save-routine':
        if (!simko_flag('routines')) {
            simko_fail(404, 'Routines are turned off.');
        }
        simko_ok(['routine' => simko_routine_save($userId, $body), 'routines' => simko_routine_rows($userId)]);
        break;
    case 'memories':
        if (!simko_flag('memory')) {
            simko_fail(404, 'Memory is turned off.');
        }
        $childId = simko_requested_child($userId, $body);
        simko_ok(['memories' => simko_memory_rows($userId, $childId)]);
        break;
    case 'forget':
        if (!simko_flag('memory')) {
            simko_fail(404, 'Memory is turned off.');
        }
        simko_memory_delete($userId, (int) ($body['memory_id'] ?? 0));
        simko_ok(['memories' => simko_memory_rows($userId, simko_requested_child($userId, $body))]);
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
