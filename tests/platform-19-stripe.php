<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

$basePort = 20000 + (getmypid() % 20000);
$mockPort = $basePort + 1;
$sitePort = $basePort + 2;
$stripePort = $basePort + 3;
$capture = sys_get_temp_dir() . '/simko-stripe-capture-' . getmypid() . '.json';
@unlink($capture);

[$mock, $mockPipes] = platform_mock($mockPort);
[$stripe, $stripePipes] = platform_stripe_mock($stripePort, $capture);

$webhookSecret = 'whsec_test_local_only';
$priceId = 'price_test_999_monthly';
$private = platform_private('stripe-billing', ['paywall' => true, 'images' => true], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'site_url' => 'https://simkosi.com',
    'billing' => ['provider' => 'stripe'],
    'stripe' => [
        'restricted_key' => 'rk_test_local_mock',
        'secret_key' => '',
        'webhook_secret' => $webhookSecret,
        'price_id' => $priceId,
        'api_base' => 'http://127.0.0.1:' . $stripePort,
        'api_version' => '2026-09-30.endive',
    ],
]);

putenv('SIMKOSI_PRIVATE=' . $private);
require_once $GLOBALS['simko_root'] . '/public_html/api/stripe.php';

$goodPayload = '{"id":"evt_sig"}';
$goodHeader = platform_stripe_sign($goodPayload, $webhookSecret, time());
platform_assert(simko_stripe_verify_signature($goodPayload, $goodHeader, $webhookSecret), 'good Stripe-Signature verifies');
platform_assert(!simko_stripe_verify_signature($goodPayload, $goodHeader, 'whsec_wrong'), 'wrong secret is rejected');
platform_assert(!simko_stripe_verify_signature($goodPayload, 't=1,v1=deadbeef', $webhookSecret), 'bad signature is rejected');
$stale = platform_stripe_sign($goodPayload, $webhookSecret, time() - 10000);
platform_assert(!simko_stripe_verify_signature($goodPayload, $stale, $webhookSecret), 'stale timestamp is rejected');

[$site, $sitePipes] = platform_site($private, $sitePort);
$email = 'stripe-' . getmypid() . '@simkosi.test';
$user = platform_signup($sitePort, $email);
$token = $user['token'];

$usage = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $token);
platform_assert($usage['status'] === 200 && ($usage['data']['plan_amount'] ?? 0) === 999, 'usage reports 999 cents');
platform_assert(($usage['data']['plan_label'] ?? '') === '$9.99/month', 'usage reports $9.99/month');
platform_assert(($usage['data']['billing']['provider'] ?? '') === 'stripe', 'usage reports stripe provider');

$blockedImage = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'A sea turtle over the reef'], $token);
platform_assert($blockedImage['status'] === 402 && !empty($blockedImage['data']['paywall']), 'free accounts cannot make pictures');

for ($i = 1; $i <= 5; $i++) {
    $turn = platform_api($sitePort, '/api/simco/turn', ['text' => 'message ' . $i], $token);
    platform_assert($turn['status'] === 200, 'free message ' . $i);
}
$sixth = platform_api($sitePort, '/api/simco/turn', ['text' => 'one more'], $token);
platform_assert($sixth['status'] === 402 && !empty($sixth['data']['paywall']), 'sixth message opens the paywall');

$checkout = platform_api($sitePort, '/api/platform', ['op' => 'checkout'], $token);
platform_assert($checkout['status'] === 200 && str_contains((string) ($checkout['data']['url'] ?? ''), 'mock-stripe-checkout'), 'mocked Stripe checkout returns a url');

$captured = null;
$deadline = microtime(true) + 2;
while (microtime(true) < $deadline) {
    if (is_file($capture)) {
        $captured = json_decode((string) file_get_contents($capture), true);
        if (is_array($captured) && (($captured['fields']['mode'] ?? '') === 'subscription') && (($captured['fields']['line_items'][0]['price'] ?? '') !== '')) {
            break;
        }
    }
    usleep(40000);
}
platform_assert(is_array($captured) && (($captured['fields']['line_items'][0]['price'] ?? '') !== ''), 'checkout payload was captured without calling Stripe');
$fields = $captured['fields'] ?? [];
platform_assert(($fields['mode'] ?? '') === 'subscription', 'checkout mode is subscription');
platform_assert(($fields['line_items'][0]['price'] ?? '') === $priceId, 'checkout uses the configured price id');
platform_assert((int) ($fields['line_items'][0]['quantity'] ?? 0) === 1, 'checkout quantity is 1');
platform_assert(!array_key_exists('payment_method_types', $fields), 'checkout omits payment_method_types');
platform_assert(str_starts_with((string) ($fields['integration_identifier'] ?? ''), 'simkosi-'), 'checkout sends integration_identifier');
platform_assert(($fields['customer_email'] ?? '') === $email, 'checkout includes the account email');
platform_assert(isset($fields['metadata']['user_id']) && $fields['metadata']['user_id'] !== '', 'checkout metadata has user_id');
platform_assert(isset($fields['subscription_data']['metadata']['user_id']), 'subscription metadata has user_id');
platform_assert(!str_contains(json_encode($fields), '900') || ($fields['line_items'][0]['price'] ?? '') === $priceId, 'payload does not charge 900 cents');
platform_assert(str_contains((string) ($captured['headers']['authorization'] ?? ''), 'rk_test_local_mock'), 'request uses the configured key');
platform_assert(($captured['headers']['stripe_version'] ?? '') === '2026-09-30.endive', 'request uses the current Stripe API version');

$userId = (int) $fields['metadata']['user_id'];
platform_assert($userId > 0, 'captured user id is numeric');

$bad = platform_post_raw($sitePort, '/api/stripe-webhook', '{"id":"evt_bad"}', [
    'Stripe-Signature' => 't=' . time() . ',v1=deadbeef',
]);
platform_assert($bad['status'] === 400, 'bad webhook signature is rejected');

function stripe_event(string $id, string $type, array $object): string
{
    return json_encode([
        'id' => $id,
        'object' => 'event',
        'type' => $type,
        'data' => ['object' => $object],
    ], JSON_UNESCAPED_SLASHES);
}

function post_event(int $port, string $secret, string $id, string $type, array $object): array
{
    $payload = stripe_event($id, $type, $object);
    return platform_post_raw($port, '/api/stripe-webhook', $payload, [
        'Stripe-Signature' => platform_stripe_sign($payload, $secret),
    ]);
}

$completed = post_event($sitePort, $webhookSecret, 'evt_checkout_1', 'checkout.session.completed', [
    'id' => 'cs_test_mock_session',
    'object' => 'checkout.session',
    'mode' => 'subscription',
    'payment_status' => 'paid',
    'client_reference_id' => (string) $userId,
    'customer' => 'cus_test_1',
    'subscription' => 'sub_test_1',
    'metadata' => ['user_id' => (string) $userId],
]);
platform_assert($completed['status'] === 200 && !empty($completed['data']['ok']), 'checkout.session.completed is accepted');

$dup = post_event($sitePort, $webhookSecret, 'evt_checkout_1', 'checkout.session.completed', [
    'id' => 'cs_test_mock_session',
    'payment_status' => 'paid',
    'metadata' => ['user_id' => (string) $userId],
]);
platform_assert($dup['status'] === 200 && !empty($dup['data']['duplicate']), 'duplicate webhook is ignored');

$paid = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $token);
platform_assert(($paid['data']['status'] ?? '') === 'paid', 'checkout completion marks the account paid');

$seventh = platform_api($sitePort, '/api/simco/turn', ['text' => 'after payment'], $token);
platform_assert($seventh['status'] === 200, 'paid accounts can send another message');

$picture = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'A sea turtle over the reef'], $token);
platform_assert($picture['status'] === 200 && !empty($picture['data']['image']['id']), 'paid accounts can make pictures');

$portal = platform_api($sitePort, '/api/platform', ['op' => 'billing-portal'], $token);
platform_assert($portal['status'] === 200 && str_contains((string) ($portal['data']['url'] ?? ''), 'mock-stripe-portal'), 'customer portal link opens from the mock');

$failed = post_event($sitePort, $webhookSecret, 'evt_fail_1', 'invoice.payment_failed', [
    'id' => 'in_test_1',
    'object' => 'invoice',
    'customer' => 'cus_test_1',
    'subscription' => 'sub_test_1',
]);
platform_assert($failed['status'] === 200 && !empty($failed['data']['ok']), 'invoice.payment_failed is accepted');
$pastDue = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $token);
platform_assert(($pastDue['data']['status'] ?? '') === 'past_due', 'failed invoice marks the account past due');
$pastImage = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'A reef at dusk'], $token);
platform_assert($pastImage['status'] === 402, 'pictures stop when payment fails');

$updated = post_event($sitePort, $webhookSecret, 'evt_sub_active', 'customer.subscription.updated', [
    'id' => 'sub_test_1',
    'object' => 'subscription',
    'status' => 'active',
    'customer' => 'cus_test_1',
    'metadata' => ['user_id' => (string) $userId],
]);
platform_assert($updated['status'] === 200, 'customer.subscription.updated is accepted');
$active = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $token);
platform_assert(($active['data']['status'] ?? '') === 'paid', 'an active subscription restores paid access');

$deleted = post_event($sitePort, $webhookSecret, 'evt_sub_deleted', 'customer.subscription.deleted', [
    'id' => 'sub_test_1',
    'object' => 'subscription',
    'status' => 'canceled',
    'customer' => 'cus_test_1',
    'metadata' => ['user_id' => (string) $userId],
]);
platform_assert($deleted['status'] === 200, 'customer.subscription.deleted is accepted');
$cancelled = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $token);
platform_assert(($cancelled['data']['status'] ?? '') === 'free', 'deleting the subscription returns the account to free');
$cancelledTurn = platform_api($sitePort, '/api/simco/turn', ['text' => 'after cancel'], $token);
platform_assert($cancelledTurn['status'] === 402 && !empty($cancelledTurn['data']['paywall']), 'cancelled accounts hit the message cap again');

platform_stop($site, $sitePipes);
platform_stop($stripe, $stripePipes);
platform_stop($mock, $mockPipes);
@unlink($capture);
fwrite(STDOUT, "stripe billing tests passed\n");
