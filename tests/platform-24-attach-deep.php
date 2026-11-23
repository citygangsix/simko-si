<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Paperclip (pictures to Grok vision, PDFs/text read on the server), DeepSearch, and agent-mode tools.
$log = sys_get_temp_dir() . '/simko-attach-calls-' . getmypid() . '.log';
@unlink($log);
putenv('MOCK_XAI_LOG=' . $log);
$mockPort = 8861;
$sitePort = 8862;
[$mock, $mockPipes] = platform_mock($mockPort);
@unlink($log);
$calls = static function () use ($log): int {
    return is_file($log) ? count(array_filter(explode("\n", (string) file_get_contents($log)))) : 0;
};
$ownerEmail = 'attach-owner-' . getmypid() . '@simkosi.test';
$private = platform_private('attach', ['search' => true, 'browse' => true, 'agents' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'owner_access' => ['emails' => [$ownerEmail], 'user_ids' => []],
    'attach_max_mb' => 1,
]);
[$site, $sitePipes] = platform_site($private, $sitePort);
$owner = platform_signup($sitePort, $ownerEmail);
$guest = platform_signup($sitePort, 'attach-guest-' . getmypid() . '@simkosi.test');
$tok = $owner['token'];

// A real 1x1 PNG.
$png = base64_encode((string) hex2bin('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
    . '1f15c4890000000d49444154789c6360f8cf00000301010018dd8db40000000049454e44ae426082'));
$pic = platform_api($sitePort, '/api/simco/turn', ['text' => 'What is this?', 'file' => ['name' => 'dot.png', 'type' => 'image/png', 'data' => $png]], $tok);
platform_assert($pic['status'] === 200 && str_contains((string) ($pic['data']['everyday'] ?? ''), 'saw a picture'), 'a PNG goes to Grok vision as an input_image');
platform_assert(($pic['data']['attachment']['kind'] ?? '') === 'image' && ($pic['data']['attachment']['name'] ?? '') === 'dot.png', 'the reply names the attached picture');
platform_assert((int) ($pic['data']['cost_ticks'] ?? 0) === 1234567, 'the exact xAI cost comes back with the reply');

$pdf = base64_encode((string) file_get_contents(__DIR__ . '/fixtures/invoice-chrome.pdf'));
$doc = platform_api($sitePort, '/api/simco/turn', ['text' => 'What is the door code?', 'file' => ['name' => 'invoice.pdf', 'type' => 'application/pdf', 'data' => $pdf]], $tok);
$reply = (string) ($doc['data']['everyday'] ?? '');
platform_assert($doc['status'] === 200 && ($doc['data']['attachment']['mime'] ?? '') === 'application/pdf' && (int) ($doc['data']['attachment']['pages'] ?? 0) === 1, 'a Chrome PDF is read on the server');
platform_assert(str_contains($reply, 'turtle-58') && str_contains($reply, '247.00'), 'the PDF text (door code, total) reaches Grok');
platform_assert(!str_contains($reply, 'JVBER'), 'raw PDF bytes are not sent to Grok');

$txt = platform_api($sitePort, '/api/simco/turn', ['text' => '', 'file' => ['name' => 'notes.md', 'type' => 'text/markdown', 'data' => base64_encode("# Notes\nThe boat leaves at 7:15.\n")]], $tok);
platform_assert($txt['status'] === 200 && str_contains((string) ($txt['data']['everyday'] ?? ''), '7:15'), 'a text file with no message is summarized');

$big = platform_api($sitePort, '/api/simco/turn', ['text' => 'hi', 'file' => ['name' => 'big.txt', 'type' => 'text/plain', 'data' => base64_encode(str_repeat('a', 1100000))]], $tok);
platform_assert($big['status'] === 413 && str_contains((string) ($big['data']['error'] ?? ''), 'under 1 MB'), 'a file over the limit is refused (413)');
$exe = platform_api($sitePort, '/api/simco/turn', ['text' => 'hi', 'file' => ['name' => 'x.exe', 'type' => 'application/octet-stream', 'data' => base64_encode("MZ\x90\x00binary\x00\x01")]], $tok);
platform_assert($exe['status'] === 415, 'an unsupported file type is refused (415)');
$scan = platform_api($sitePort, '/api/simco/turn', ['text' => 'hi', 'file' => ['name' => 'scan.pdf', 'type' => 'application/pdf', 'data' => base64_encode("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF")]], $tok);
platform_assert($scan['status'] === 422, 'a PDF with no text gives a clear 422');

$before = $calls();
$no = platform_api($sitePort, '/api/simco/turn', ['text' => 'hi', 'file' => ['name' => 'dot.png', 'type' => 'image/png', 'data' => $png]], $guest['token']);
platform_assert($no['status'] === 403, 'a non-owner upload is refused like chat');
platform_assert($calls() === $before, 'no xAI call for the refused upload');

$deep = platform_api($sitePort, '/api/simco/turn', ['text' => 'Latest on reef restoration?', 'deep_search' => true], $tok);
platform_assert($deep['status'] === 200 && str_starts_with((string) ($deep['data']['everyday'] ?? ''), '[deep] '), 'DeepSearch adds its research instructions');
platform_assert(!empty($deep['data']['deep_search']) && ($deep['data']['reasoning_effort'] ?? '') === 'high', 'DeepSearch defaults to high effort');
$urls = array_map(static fn($s) => is_array($s) ? ($s['url'] ?? '') : $s, $deep['data']['sources'] ?? []);
platform_assert(in_array('https://example.com/second', $urls, true) && count($urls) >= 2, 'DeepSearch sources are listed');
platform_assert((int) ($deep['data']['search_calls']['web'] ?? 0) >= 1 && (int) ($deep['data']['search_calls']['x'] ?? 0) >= 1, 'DeepSearch reports its web and X search counts');
$plain = platform_api($sitePort, '/api/simco/turn', ['text' => 'Latest on reef restoration?'], $tok);
platform_assert(!str_starts_with((string) ($plain['data']['everyday'] ?? ''), '[deep] ') && empty($plain['data']['deep_search']), 'DeepSearch stays off unless toggled');

// Agent mode: tools stream (Responses API), finishes with cost and sources.
$agent = platform_api($sitePort, '/api/platform', ['op' => 'create-agent', 'name' => 'Scout', 'persona' => 'Brief.'], $tok);
$agentId = (int) ($agent['data']['agent']['id'] ?? 0);
$stream = platform_api($sitePort, '/api/agent-stream', ['agent_id' => $agentId, 'text' => 'Find reef news'], $tok);
$raw = (string) ($stream['data']['raw'] ?? '');
platform_assert($stream['status'] === 200 && str_contains($raw, '"delta"'), 'agent mode streams deltas');
platform_assert(preg_match('/"done":true[^\n]*"cost_ticks":1234567/', $raw) === 1, 'agent mode ends with the exact cost');
platform_assert(str_contains($raw, '"sources"'), 'agent mode reports its search sources');
$costLog = $private . '/data/xai-costs.log';
platform_assert(is_file($costLog) && substr_count((string) file_get_contents($costLog), "\n") >= 5, 'every xAI call is written to the cost log');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
@unlink($log);
fwrite(STDOUT, "attach + DeepSearch + agent tools tests passed\n");
