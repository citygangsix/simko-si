<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// Several attachments with Word and Excel, chat share links, the allowed-sites list,
// reply language and the DeepSearch multi-agent model.
$bodies = sys_get_temp_dir() . '/simko-32-bodies-' . getmypid() . '.log';
putenv('MOCK_XAI_BODIES=' . $bodies);
[$mock, $mockPipes] = platform_mock(8869);
$private = platform_private('files-share', ['search' => true, 'browse' => true, 'shares' => true, 'images' => true, 'paywall' => false], ['xai_base_url' => 'http://127.0.0.1:8869/v1']);
[$site, $sitePipes] = platform_site($private, 8868);
$u = platform_signup(8868, 'files-' . getmypid() . '@simkosi.test');
$t = $u['token'];
$fx = __DIR__ . '/fixtures/';
$b64 = fn (string $f): string => base64_encode((string) file_get_contents($fx . $f));
$png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

// Word + Excel + 2 pictures in one message.
@unlink($bodies);
$r = platform_api(8868, '/api/simco/turn', ['text' => 'What is in these?', 'files' => [
    ['name' => 'reef-notes.docx', 'type' => '', 'data' => $b64('reef-notes.docx')],
    ['name' => 'reef-stock.xlsx', 'type' => '', 'data' => $b64('reef-stock.xlsx')],
    ['name' => 'a.png', 'type' => 'image/png', 'data' => $png],
    ['name' => 'b.png', 'type' => 'image/png', 'data' => $png],
]], $t);
platform_assert($r['status'] === 200, 'four files in one message are accepted');
$reply = (string) ($r['data']['everyday'] ?? '');
platform_assert(str_contains($reply, 'The gate code is coral-42'), 'Word text is read');
platform_assert((str_contains($reply, "Clownfish\t17") || str_contains($reply, 'Clownfish\\t17')) && str_contains($reply, '[Sheet Stock]'), 'Excel cells are read with the sheet name');
platform_assert(count($r['data']['attachments'] ?? []) === 4, 'all four files are listed back');
platform_assert(substr_count((string) @file_get_contents($bodies), 'input_image') === 2, 'both pictures go to Grok');
$five = array_fill(0, 5, ['name' => 'a.png', 'type' => 'image/png', 'data' => $png]);
platform_assert(platform_api(8868, '/api/simco/turn', ['text' => 'x', 'files' => $five], $t)['status'] === 400, 'a fifth file is refused');
$old = platform_api(8868, '/api/simco/turn', ['text' => 'One file', 'file' => ['name' => 'reef-notes.docx', 'type' => '', 'data' => $b64('reef-notes.docx')]], $t);
platform_assert($old['status'] === 200 && str_contains((string) $old['data']['everyday'], 'coral-42'), 'the older single-file form still works');

// Reply language.
@unlink($bodies);
platform_api(8868, '/api/simco/turn', ['text' => 'Hola', 'lang' => 'es'], $t);
platform_assert(str_contains((string) @file_get_contents($bodies), 'write every reply in Spanish'), 'a picked reply language reaches Grok');
@unlink($bodies);
platform_api(8868, '/api/simco/turn', ['text' => 'Hola', 'lang' => 'xx'], $t);
$sent = (string) @file_get_contents($bodies);
platform_assert(!str_contains($sent, "Language rule") && str_contains($sent, 'reply in their language'), 'an unknown language falls back to the writer\'s language');

// DeepSearch uses the multi-agent model with 4 agents unless a model was picked.
@unlink($bodies);
platform_api(8868, '/api/simco/turn', ['text' => 'Research reefs', 'deep_search' => true], $t);
$sent = (string) @file_get_contents($bodies);
platform_assert(str_contains($sent, '"model":"grok-4.20-multi-agent-0309"') && str_contains($sent, '"effort":"medium"'), 'DeepSearch uses the multi-agent model, 4 agents');
platform_assert(str_contains($sent, '"x_search"'), 'X search is offered to Grok');

// Share a chat.
$chat = platform_api(8868, '/api/sessions', ['op' => 'create', 'title' => 'Reef chat'], $t);
$cid = (string) ($chat['data']['session']['id'] ?? '');
platform_api(8868, '/api/sessions', ['op' => 'append', 'session_id' => $cid, 'role' => 'user', 'text' => 'Tell me about turtles <b>now</b>'], $t);
platform_api(8868, '/api/sessions', ['op' => 'append', 'session_id' => $cid, 'role' => 'assistant', 'text' => 'Turtles are calm.'], $t);
$share = platform_api(8868, '/api/platform', ['op' => 'share-chat', 'chat_id' => $cid], $t);
platform_assert($share['status'] === 200 && preg_match('/token=([a-f0-9]{48})$/', (string) ($share['data']['share']['url'] ?? ''), $m) === 1, 'a chat share link is made');
$page = (string) @file_get_contents('http://127.0.0.1:8868/api/share?token=' . $m[1]);
platform_assert(str_contains($page, 'Reef chat') && str_contains($page, 'Tell me about turtles &lt;b&gt;now&lt;/b&gt;'), 'the shared page shows the chat, escaped');
$other = platform_signup(8868, 'files-other-' . getmypid() . '@simkosi.test');
platform_assert(platform_api(8868, '/api/platform', ['op' => 'share-chat', 'chat_id' => $cid], $other['token'])['status'] === 404, 'nobody else can share my chat');
platform_api(8868, '/api/platform', ['op' => 'revoke-share', 'share_token' => $m[1]], $t);
$gone = @file_get_contents('http://127.0.0.1:8868/api/share?token=' . $m[1]);
platform_assert($gone === false, 'a revoked chat link stops working');

// Allowed-sites list.
$sites = platform_api(8868, '/api/platform', ['op' => 'browse-sites'], $t);
platform_assert(in_array('wikipedia.org', $sites['data']['sites'] ?? [], true), 'a default allowed-sites list exists');
$saved = platform_api(8868, '/api/platform', ['op' => 'browse-sites', 'sites' => "https://www.Example.org/path\n*.gov.uk\nnot a site\nexample.org"], $t);
platform_assert(($saved['data']['sites'] ?? null) === ['www.example.org', 'gov.uk', 'example.org'], 'the list is cleaned and de-duplicated');
$blocked = platform_api(8868, '/api/simco/turn', ['text' => 'Read https://news.ycombinator.com/ please'], $t);
platform_assert(str_contains((string) ($blocked['data']['pages'][0]['error'] ?? ''), 'allowed-sites list'), 'a pasted link to an unlisted site is not opened');
platform_assert(platform_api(8868, '/api/platform', ['op' => 'browse', 'url' => 'https://news.ycombinator.com/'], $t)['status'] === 403, 'the Read a page card follows the same list');
$reset = platform_api(8868, '/api/platform', ['op' => 'browse-sites', 'reset' => true], $t);
platform_assert(in_array('wikipedia.org', $reset['data']['sites'] ?? [], true), 'the default list can be restored');

// Picture editing goes to /v1/images/edits with the uploaded picture.
@unlink($bodies);
$edit = platform_api(8868, '/api/platform', ['op' => 'imagine', 'prompt' => 'Make it a pencil sketch', 'source' => 'data:image/png;base64,' . $png], $t);
$sent = (string) @file_get_contents($bodies);
platform_assert($edit['status'] === 200 && !empty($edit['data']['image']['id']), 'an edited picture comes back');
platform_assert(str_contains($sent, '"image":{"url":"data:image\/png;base64,'), 'the uploaded picture is sent for editing');
$badEdit = platform_api(8868, '/api/platform', ['op' => 'imagine', 'prompt' => 'x', 'source' => base64_encode('GIF89a not a png')], $t);
platform_assert($badEdit['status'] === 415, 'only JPEG and PNG can be edited');

platform_stop($site, $sitePipes);
platform_stop($mock, $mockPipes);
@unlink($bodies);
fwrite(STDOUT, "files, share and browse tests passed\n");
