<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Pictures for the owner (not billed) and paid subscribers (Grok's cost recorded per picture). Mocked xAI only.
$log = sys_get_temp_dir() . '/simko-img-calls-' . getmypid() . '.log';
@unlink($log);
putenv('MOCK_XAI_LOG=' . $log);
$mockPort = 8851;
$sitePort = 8852;
[$mock, $mockPipes] = platform_mock($mockPort);
@unlink($log);
$calls = static function () use ($log): int {
    return is_file($log) ? count(array_filter(explode("\n", (string) file_get_contents($log)))) : 0;
};
$ownerEmail = 'owner-img-' . getmypid() . '@simkosi.test';
$private = platform_private('imgbill', ['images' => true, 'paywall' => true, 'search' => true], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
    'images_daily_cap' => 3,
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$owner = platform_signup($sitePort, $ownerEmail);
$sub = platform_signup($sitePort, 'sub-img-' . getmypid() . '@simkosi.test');
$free = platform_signup($sitePort, 'free-img-' . getmypid() . '@simkosi.test');

// Simulate an active paid subscription (what the Stripe webhook writes). No real charge.
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$subId = (int) $db->query("SELECT id FROM users WHERE email LIKE 'sub-img-%'")->fetchColumn();
$db->prepare("INSERT INTO subscriptions (user_id, status, trial_until, updated_at) VALUES (?, 'paid', 0, ?)")->execute([$subId, time()]);

$q = platform_api($sitePort, '/api/platform', ['op' => 'image-quote'], $owner['token']);
platform_assert($q['status'] === 200 && $q['data']['access']['role'] === 'owner' && str_contains($q['data']['access']['quote'], 'not billed'), 'the owner sees the price and that he is not billed');
$o = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'a blue circle'], $owner['token']);
platform_assert($o['status'] === 200 && $o['data']['image']['cost_ticks'] === 400000000 && $o['data']['image']['cost_source'] === 'xai_usage', 'the owner picture records the real xAI cost');
platform_assert($o['data']['image']['charge_status'] === 'owner_not_billed' && $o['data']['ledger']['month_pending_ticks'] === 0, 'the owner is not billed');
platform_assert($calls() === 1, 'one image call for the owner');

$sq = platform_api($sitePort, '/api/platform', ['op' => 'image-quote'], $sub['token']);
platform_assert($sq['data']['access']['role'] === 'subscriber' && $sq['data']['access']['quote'] === 'This picture costs $0.04. It is added to your bill.', 'a subscriber sees "This picture costs $0.04" before making one');
$s1 = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'a red square'], $sub['token']);
platform_assert($s1['status'] === 200 && $s1['data']['image']['charge_status'] === 'pending' && $s1['data']['image']['cost_label'] === '$0.04', 'a subscriber picture is made and $0.04 is recorded as pending');
$s2 = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'a green triangle NOCOST'], $sub['token']);
platform_assert($s2['status'] === 200 && $s2['data']['image']['cost_source'] === 'price_list' && $s2['data']['image']['cost_ticks'] === 400000000, 'without usage in the response the documented price is used');
platform_assert($s2['data']['ledger']['month_pending_ticks'] === 800000000 && $s2['data']['ledger']['month_pending_count'] === 2, 'the subscriber ledger totals $0.08 for two pictures');
$usage = platform_api($sitePort, '/api/platform', ['op' => 'usage'], $sub['token']);
platform_assert(($usage['data']['image_ledger']['month_pending_label'] ?? '') === '$0.08', 'the usage view shows the picture charges');
$img = @file_get_contents('http://127.0.0.1:' . $sitePort . '/api/image?id=' . $s1['data']['image']['id'], false, stream_context_create(['http' => ['header' => "Authorization: Bearer {$sub['token']}\r\n", 'ignore_errors' => true]]));
platform_assert(is_string($img) && str_starts_with($img, "\x89PNG"), 'the subscriber can open the picture');
$s3 = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'a yellow star'], $sub['token']);
platform_assert($s3['status'] === 200, 'third picture is within the cap of 3');
$before = $calls();
$s4 = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'one more'], $sub['token']);
platform_assert($s4['status'] === 429 && $calls() === $before, 'the daily cap still applies, with no xAI call');

// The subscriber exception is pictures only: chat and voice stay owner-only.
$chat = platform_api($sitePort, '/api/simco/turn', ['text' => 'hi'], $sub['token']);
platform_assert($chat['status'] === 403, 'a subscriber chat is still refused (owner lock intact)');
$stt = platform_api($sitePort, '/api/voice/transcribe', ['audio' => base64_encode('RIFF....'), 'mime' => 'audio/wav'], $sub['token']);
platform_assert($stt['status'] === 403, 'a subscriber transcription is still refused');
platform_assert($calls() === $before, 'no xAI call for the refused subscriber chat or voice');

$db->prepare("UPDATE subscriptions SET status = 'past_due' WHERE user_id = ?")->execute([$subId]);
$pd = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'past due try'], $sub['token']);
platform_assert($pd['status'] === 402 && $calls() === $before, 'a past-due subscriber is refused with no xAI call');
$f = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'a blue circle'], $free['token']);
platform_assert($f['status'] === 402 && str_contains((string) $f['data']['error'], 'Subscribe to make pictures'), 'a free account is told to subscribe');
$fq = platform_api($sitePort, '/api/platform', ['op' => 'image-quote'], $free['token']);
platform_assert($fq['data']['access']['allowed'] === false, 'a free account cannot start a picture');
$anon = platform_api($sitePort, '/api/platform', ['op' => 'imagine', 'prompt' => 'x']);
platform_assert($anon['status'] === 401, 'signed out is refused');
platform_assert($calls() === $before, 'no xAI call for free or signed-out requests');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
@unlink($log);
fwrite(STDOUT, "image billing tests passed\n");
