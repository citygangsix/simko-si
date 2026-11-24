<?php
declare(strict_types=1);

require __DIR__ . '/bootstrap.php';
require_once __DIR__ . '/usage.php';
require_once __DIR__ . '/stripe.php';
require_once __DIR__ . '/approvals.php';
require_once __DIR__ . '/recall.php';
require_once __DIR__ . '/routines.php';
require_once __DIR__ . '/images.php';
require_once __DIR__ . '/shares.php';
require_once __DIR__ . '/oauth.php';
require_once __DIR__ . '/vault.php';
require_once __DIR__ . '/connectors.php';
require_once __DIR__ . '/agents.php';
require_once __DIR__ . '/team.php';
require_once __DIR__ . '/browse.php';
require_once __DIR__ . '/code.php';

$body = simko_require_post_json();
$op = (string) ($body['op'] ?? '');
if ($op === 'oauth-start') {
    simko_ok(simko_oauth_start((string) ($body['provider'] ?? '')));
}
$user = simko_require_user();
$userId = (int) $user['id'];

if (str_starts_with($op, 'code-') || $op === 'cursor-check') {
    if (!simko_flag('code')) {
        simko_fail(404, 'The Code tab is turned off.');
    }
    // Coding jobs spend on the owner's keys: owner only, refused before any outside call.
    simko_require_grok_owner($user);
    @set_time_limit(200);
}

switch ($op) {
    case 'models':
        $cfgModel = trim((string) (simko_config_or_empty()['model'] ?? 'grok-4.7'));
        simko_ok([
            'models' => simko_models(),
            'default' => $cfgModel === '' ? 'grok-4.7' : $cfgModel,
            'spend' => simko_can_use_grok($user) ? simko_spend_status($user) : null,
        ]);
        break;
    case 'code-jobs':
        $cursor = simko_cursor_settings();
        simko_ok([
            'jobs' => simko_code_list($userId),
            'engines' => [
                'grok' => ['ready' => true, 'model' => simko_code_model(), 'billing' => 'xAI key (owner)'],
                'cursor' => ['ready' => $cursor['connected'], 'allow_launch' => $cursor['allow_launch'], 'billing' => 'Cursor account (paid agent time)'],
            ],
        ]);
        break;
    case 'code-start':
        $engine = (string) ($body['engine'] ?? 'grok') === 'cursor' ? 'cursor' : 'grok';
        $job = simko_code_start($user, (string) ($body['prompt'] ?? ''), $engine, [
            'confirm_paid' => !empty($body['confirm_paid']),
            'dry_run' => !empty($body['dry_run']),
        ]);
        if ($job['engine'] === 'grok' && $job['status'] === 'planning') {
            simko_code_reply_then_continue(['job' => simko_code_public($job)]);
            simko_code_background($job, 'build');
            exit;
        }
        simko_ok(['job' => simko_code_public($job)]);
        break;
    case 'code-job':
        $job = simko_code_load($userId, (string) ($body['job_id'] ?? ''));
        if (($job['engine'] ?? '') === 'cursor') {
            $job = simko_cursor_refresh($job);
        }
        if (in_array($job['status'], ['planning', 'fixing'], true) && (int) ($job['updated_at'] ?? $job['created_at']) < time() - 360) {
            $job['status'] = ($job['files'] ?? []) ? 'tests_failed' : 'failed';
            $job['error'] = 'The build stopped before Grok finished. Try again.';
            simko_code_save($job);
        }
        simko_ok(['job' => simko_code_public($job)]);
        break;
    case 'code-verify':
        $job = simko_code_load($userId, (string) ($body['job_id'] ?? ''));
        $job = simko_code_record_verify($job, $body['results'] ?? [], $body['errors'] ?? []);
        simko_ok(['job' => simko_code_public($job)]);
        break;
    case 'code-fix':
        $job = simko_code_fix(simko_code_load($userId, (string) ($body['job_id'] ?? '')));
        simko_code_reply_then_continue(['job' => simko_code_public($job)]);
        simko_code_background($job, 'fix');
        exit;
        break;
    case 'code-zip':
        $job = simko_code_load($userId, (string) ($body['job_id'] ?? ''));
        if (empty($job['files'])) {
            simko_fail(400, 'This job has no files yet.');
        }
        $name = (preg_replace('/[^a-z0-9\-]+/', '-', strtolower((string) ($job['title'] ?? 'project'))) ?: 'project');
        simko_ok(['name' => trim(substr($name, 0, 40), '-') . '.zip', 'zip_b64' => base64_encode(simko_code_zip($job))]);
        break;
    case 'cursor-check':
        simko_ok(['cursor' => simko_cursor_check()]);
        break;
    case 'usage':
        if (!simko_flag('paywall')) {
            simko_fail(404, 'Usage is turned off.');
        }
        $snap = simko_usage_snapshot($userId);
        $snap['events'] = simko_usage_events($userId);
        $snap['image_ledger'] = simko_flag('images') ? simko_image_ledger($userId) : null;
        $snap['plan_label'] = simko_plan_label();
        $snap['plan_amount'] = simko_plan_amount();
        $provider = simko_billing_provider();
        $connected = $provider === 'square'
            ? simko_square_settings()['connected']
            : simko_stripe_settings()['connected'];
        $imageBilling = simko_image_billing_settings();
        $snap['billing'] = [
            'provider' => $provider,
            'connected' => $connected,
            'image_billing_mode' => $imageBilling['mode'],
            'image_billing_ready' => $imageBilling['ready'],
        ];
        $snap['square'] = ['connected' => simko_square_settings()['connected'], 'plan_label' => simko_plan_label()];
        simko_ok($snap);
        break;
    case 'checkout':
        if (!simko_flag('paywall')) {
            simko_fail(404, 'Usage is turned off.');
        }
        simko_guard_approval($userId, $body, 'spend', 'Pay ' . simko_plan_label() . ' for Simko SI', ['op' => 'checkout']);
        $result = simko_billing_provider() === 'square'
            ? simko_square_checkout($userId)
            : simko_stripe_checkout($userId, $user);
        if (!empty($result['error']) && empty($result['url'])) {
            simko_fail(402, (string) $result['error'], ['connected' => !empty($result['connected'])]);
        }
        simko_ok($result);
        break;
    case 'confirm-checkout':
        if (!simko_flag('paywall')) {
            simko_fail(404, 'Usage is turned off.');
        }
        if (simko_billing_provider() === 'stripe') {
            // Access comes from the Stripe webhook, not from the success page.
            simko_ok(simko_usage_snapshot($userId));
        }
        $result = simko_square_confirm($userId, trim((string) ($body['link_id'] ?? '')));
        if (empty($result['paid'])) {
            simko_fail(402, (string) ($result['error'] ?? 'Nothing was charged.'));
        }
        simko_ok(simko_usage_snapshot($userId));
        break;
    case 'billing-portal':
        if (!simko_flag('paywall')) {
            simko_fail(404, 'Usage is turned off.');
        }
        if (simko_billing_provider() !== 'stripe') {
            simko_fail(400, 'The customer portal is available when billing uses Stripe.');
        }
        $result = simko_stripe_portal($userId);
        if (!empty($result['error']) && empty($result['url'])) {
            simko_fail(402, (string) $result['error'], ['connected' => !empty($result['connected'])]);
        }
        simko_ok($result);
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
    case 'store-steps':
        if (!simko_flag('store')) {
            simko_fail(404, 'Store notes are turned off.');
        }
        simko_ok([
            'published' => false,
            'url' => 'https://simkosi.com',
            'fees' => [
                'apple' => 'US$99 per year for the Apple Developer Program',
                'google' => 'US$25 once for the Play Console account',
            ],
            'steps' => [
                'Point the wrapper at https://simkosi.com. That is already in mobile/capacitor.config.json.',
                'Leave platform flags off until the mockups are signed off.',
                'Apple: enroll, register com.simkosi.simcosi, archive in Xcode, upload. Joseph decides on the $99 membership.',
                'Google: register Play Console, build an Android App Bundle, upload. The account fee is $25 once.',
                'Keep the $9.99/month plan on the website Stripe checkout. Do not add an in-app purchase from here.',
            ],
        ]);
        break;
    case 'browse':
        if (!simko_flag('browse')) {
            simko_fail(404, 'Page reading is turned off.');
        }
        simko_require_grok_user($user);
        simko_ok(simko_browse_fetch((string) ($body['url'] ?? '')));
        break;
    case 'browse-sites':
        if (!simko_flag('browse')) {
            simko_fail(404, 'Page reading is turned off.');
        }
        simko_require_grok_owner($user);
        if (array_key_exists('sites', $body)) {
            simko_setting_set('browse_sites', simko_browse_clean_sites($body['sites']));
        } elseif (!empty($body['reset'])) {
            simko_setting_set('browse_sites', simko_browse_default_sites());
        }
        simko_ok(['sites' => simko_browse_sites(), 'defaults' => simko_browse_default_sites(),
            'config_list' => simko_browse_allow() !== []]);
        break;
    case 'call-status':
        if (!simko_flag('calls')) {
            simko_fail(404, 'Calls are turned off.');
        }
        $provider = trim((string) (simko_config_or_empty()['calls']['provider'] ?? ''));
        simko_ok([
            'enabled' => false,
            'provider' => $provider === '' ? null : $provider,
            'reason' => 'Phone calls are not connected. They cost money per minute, so this screen stays disabled until a provider is chosen.',
        ]);
        break;
    case 'publish-template':
        if (!simko_flag('team')) {
            simko_fail(404, 'Templates are turned off.');
        }
        simko_ok(['template' => simko_template_create($userId, (int) ($body['agent_id'] ?? 0))]);
        break;
    case 'invite':
        if (!simko_flag('team')) {
            simko_fail(404, 'Team invites are turned off.');
        }
        simko_ok(['invite' => simko_team_invite($userId, (string) ($body['email'] ?? ''), (string) ($body['role'] ?? ''))]);
        break;
    case 'accept-invite':
        if (!simko_flag('team')) {
            simko_fail(404, 'Team invites are turned off.');
        }
        simko_ok(['membership' => simko_team_accept($userId, (string) $user['email'], (string) ($body['invite_token'] ?? ''))]);
        break;
    case 'team':
        if (!simko_flag('team')) {
            simko_fail(404, 'Team invites are turned off.');
        }
        simko_ok(['members' => simko_team_members($userId)]);
        break;
    case 'agents':
        if (!simko_flag('agents')) {
            simko_fail(404, 'Side-by-side agents are turned off.');
        }
        simko_ok(['agents' => simko_agent_rows($userId)]);
        break;
    case 'create-agent':
        if (!simko_flag('agents')) {
            simko_fail(404, 'Side-by-side agents are turned off.');
        }
        simko_ok(['agent' => simko_agent_create($userId, (string) ($body['name'] ?? ''), (string) ($body['persona'] ?? '')), 'agents' => simko_agent_rows($userId)]);
        break;
    case 'hand-agent':
        if (!simko_flag('agents')) {
            simko_fail(404, 'Side-by-side agents are turned off.');
        }
        simko_agent_hand($userId, (int) ($body['from_id'] ?? 0), (int) ($body['to_id'] ?? 0), (string) ($body['text'] ?? ''));
        simko_ok();
        break;
    case 'connectors':
        if (!simko_flag('connectors')) {
            simko_fail(404, 'Connectors are turned off.');
        }
        simko_ok(['connectors' => simko_connector_list($userId)]);
        break;
    case 'connector-start':
        if (!simko_flag('connectors')) {
            simko_fail(404, 'Connectors are turned off.');
        }
        simko_ok(simko_connector_start($userId, (string) ($body['provider'] ?? '')));
        break;
    case 'connector-refresh':
        if (!simko_flag('connectors')) {
            simko_fail(404, 'Connectors are turned off.');
        }
        simko_ok(simko_connector_refresh($userId, (string) ($body['provider'] ?? '')));
        break;
    case 'connector-disconnect':
        if (!simko_flag('connectors')) {
            simko_fail(404, 'Connectors are turned off.');
        }
        simko_connector_disconnect($userId, (string) ($body['provider'] ?? ''));
        simko_ok(['connectors' => simko_connector_list($userId)]);
        break;
    case 'vault-list':
        if (!simko_flag('vault')) {
            simko_fail(404, 'The vault is turned off.');
        }
        simko_ok(['items' => simko_vault_list($userId)]);
        break;
    case 'vault-put':
        if (!simko_flag('vault')) {
            simko_fail(404, 'The vault is turned off.');
        }
        simko_ok(['item' => simko_vault_put($userId, (string) ($body['label'] ?? ''), (string) ($body['value'] ?? ''), (string) ($body['passphrase'] ?? ''))]);
        break;
    case 'vault-reveal':
        if (!simko_flag('vault')) {
            simko_fail(404, 'The vault is turned off.');
        }
        simko_ok(['value' => simko_vault_reveal($userId, (int) ($body['item_id'] ?? 0), (string) ($body['passphrase'] ?? ''))]);
        break;
    case 'share-lifebook':
        if (!simko_flag('shares')) {
            simko_fail(404, 'Sharing is turned off.');
        }
        simko_ok(['share' => simko_share_create($userId)]);
        break;
    case 'share-chat':
        if (!simko_flag('shares')) {
            simko_fail(404, 'Sharing is turned off.');
        }
        simko_ok(['share' => simko_share_chat($userId, (string) ($body['chat_id'] ?? ''))]);
        break;
    case 'revoke-share':
        if (!simko_flag('shares')) {
            simko_fail(404, 'Sharing is turned off.');
        }
        simko_share_revoke($userId, (string) ($body['share_token'] ?? ''));
        simko_ok();
        break;
    case 'imagine':
        if (!simko_flag('images')) {
            simko_fail(404, 'Pictures are turned off.');
        }
        // Owner (not billed) or an active paid subscriber (charged Grok's cost); everyone else is refused
        // inside simko_image_generate before any xAI call.
        $childId = simko_requested_child($userId, $body);
        $image = simko_image_generate($user, (string) ($body['prompt'] ?? ''), $childId,
            isset($body['source']) && is_string($body['source']) ? $body['source'] : null);
        simko_ok([
            'image' => $image,
            'images' => simko_image_rows($userId),
            'access' => simko_image_access($user),
            'ledger' => simko_image_ledger($userId),
        ]);
        break;
    case 'image-quote':
        if (!simko_flag('images')) {
            simko_fail(404, 'Pictures are turned off.');
        }
        simko_ok(['access' => simko_image_access($user), 'ledger' => simko_image_ledger($userId)]);
        break;
    case 'images':
        if (!simko_flag('images')) {
            simko_fail(404, 'Pictures are turned off.');
        }
        simko_ok([
            'images' => simko_image_rows($userId),
            'access' => simko_image_access($user),
            'ledger' => simko_image_ledger($userId),
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
    case 'forget-all':
        if (!simko_flag('memory')) {
            simko_fail(404, 'Memory is turned off.');
        }
        // The panel asks first; the request must say so too.
        if (($body['confirm'] ?? '') !== 'all') {
            simko_fail(400, 'Confirm to delete all memories.');
        }
        $childId = simko_requested_child($userId, $body);
        $deleted = simko_memory_clear($userId, $childId);
        simko_ok(['deleted' => $deleted, 'memories' => simko_memory_rows($userId, $childId)]);
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
