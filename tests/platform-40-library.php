<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// P0 saved file library: upload once to (mock) xAI Files, reuse by file id in chat, owner-only, caps, dedupe, delete.
$site = 9140;
$mockPort = 9141;
platform_require_free_port($site);
platform_require_free_port($mockPort);
$log = sys_get_temp_dir() . '/simko-p0lib-' . getmypid() . '.log';
@unlink($log);
putenv('MOCK_XAI_P0_LOG=' . $log);
platform_mock($mockPort);
$private = platform_private('p0lib', ['library' => true, 'search' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'library' => ['max_file_mb' => 1, 'max_total_mb' => 2, 'max_files' => 4],
]);
[$proc, $pipes] = platform_site($private, $site);
$a = platform_signup($site, 'liba-' . getmypid() . '@simkosi.test');
$b = platform_signup($site, 'libb-' . getmypid() . '@simkosi.test');
$api = static fn (array $body, array $who) => platform_api($site, '/api/platform', $body, $who['token']);
$xlog = static fn (): array => file_exists($log) ? (file($log, FILE_IGNORE_NEW_LINES) ?: []) : [];
$text = static fn (string $s) => base64_encode($s);

// Auth and CSRF like every platform op.
platform_assert(platform_api($site, '/api/platform', ['op' => 'library-list'])['status'] === 401, 'signed-out library-list is 401');
$csrf = platform_post_raw($site, '/api/platform', json_encode(['op' => 'library-list', 'token' => $a['token']]), ['Origin' => 'https://evil.example']);
platform_assert($csrf['status'] === 403, 'cross-site request is refused (403)');
platform_assert($api(['op' => 'task-list'], $a)['status'] === 404 && $api(['op' => 'mcp-list'], $a)['status'] === 404, 'features with their flag off answer 404');

// Happy path: save, dedupe, list.
$s1 = $api(['op' => 'library-save', 'name' => 'tile-quote.txt', 'data' => $text("Tile quote: 120 sq ft porcelain, \$1,840.\n")], $a);
platform_assert($s1['status'] === 200 && ($s1['data']['file']['ready'] ?? false) === true && $s1['data']['deduped'] === false, 'text file saved and uploaded to xAI Files');
$id1 = (string) $s1['data']['file']['id'];
platform_assert(count(array_filter($xlog(), fn ($l) => str_starts_with($l, 'POST /v1/files '))) === 1, 'one Files upload with purpose=assistants');
$userA = (int) (new PDO('sqlite:' . $private . '/data/simko.sqlite'))->query("SELECT id FROM users WHERE email LIKE 'liba-%'")->fetchColumn();
platform_assert(is_file($private . '/data/library/u' . $userA . '/' . $id1 . '.bin'), 'bytes kept in the private data folder');
$dup = $api(['op' => 'library-save', 'name' => 'copy.txt', 'data' => $text("Tile quote: 120 sq ft porcelain, \$1,840.\n")], $a);
platform_assert($dup['status'] === 200 && $dup['data']['deduped'] === true && $dup['data']['file']['id'] === $id1, 'same bytes return the saved copy');
platform_assert(count(array_filter($xlog(), fn ($l) => str_starts_with($l, 'POST /v1/files '))) === 1, 'no second upload for a duplicate');
$list = $api(['op' => 'library-list'], $a);
platform_assert(count($list['data']['files']) === 1 && $list['data']['usage']['files'] === 1, 'library lists the file with usage');
platform_assert(count($api(['op' => 'library-list', 'q' => 'tile'], $a)['data']['files']) === 1 && count($api(['op' => 'library-list', 'q' => 'zzz'], $a)['data']['files']) === 0, 'name search');

// Owner-only.
platform_assert($api(['op' => 'library-list'], $b)['data']['files'] === [], 'another account sees none of these files');
platform_assert($api(['op' => 'library-delete', 'file_id' => $id1], $b)['status'] === 404, 'another account cannot delete the file (404)');
platform_assert($api(['op' => 'library-rename', 'file_id' => $id1, 'name' => 'x.txt'], $b)['status'] === 404, 'another account cannot rename the file (404)');
$steal = platform_api($site, '/api/simco/turn', ['text' => 'what is in it?', 'library_file_ids' => [$id1]], $b['token']);
platform_assert($steal['status'] === 404, 'another account cannot use the file in chat (404)');

// Caps and types.
$big = $api(['op' => 'library-save', 'name' => 'big.txt', 'data' => $text(str_repeat('a', 1100000))], $a);
platform_assert($big['status'] === 413 && ($big['data']['cap'] ?? '') === 'file_size', 'file over the per-file cap is 413');
$bin = $api(['op' => 'library-save', 'name' => 'tool.exe', 'data' => base64_encode("MZ\x00\x01\x02\x03binary")], $a);
platform_assert($bin['status'] === 415, 'unsupported type is 415');
platform_assert($api(['op' => 'library-save', 'name' => 'b1.txt', 'data' => $text(str_repeat('b', 900000))], $a)['status'] === 200, 'second file saved');
platform_assert($api(['op' => 'library-save', 'name' => 'b2.txt', 'data' => $text(str_repeat('c', 900000))], $a)['status'] === 200, 'third file saved');
$tot = $api(['op' => 'library-save', 'name' => 'b3.txt', 'data' => $text(str_repeat('d', 500000))], $a);
platform_assert($tot['status'] === 409 && ($tot['data']['cap'] ?? '') === 'total_size', 'account total size cap is 409');
platform_assert($api(['op' => 'library-save', 'name' => 's2.txt', 'data' => $text('small two')], $a)['status'] === 200, 'fourth small file saved');
$cnt = $api(['op' => 'library-save', 'name' => 's3.txt', 'data' => $text('small three')], $a);
platform_assert($cnt['status'] === 409 && ($cnt['data']['cap'] ?? '') === 'file_count', 'account file count cap is 409');

// Chat: input_file part by xAI file id.
$turn = platform_api($site, '/api/simco/turn', ['text' => 'What does the quote cost?', 'library_file_ids' => [$id1]], $a['token']);
platform_assert($turn['status'] === 200 && str_contains($turn['data']['everyday'] ?? '', '[files:file-mock-'), 'chat sends the saved file as an input_file part: ' . ($turn['data']['everyday'] ?? json_encode($turn['data'])));
$after = $api(['op' => 'library-list', 'q' => 'tile'], $a)['data']['files'][0];
platform_assert($after['use_count'] === 1 && $after['last_used_at'] !== null, 'use count and last used are recorded');
$many = platform_api($site, '/api/simco/turn', ['text' => 'x', 'library_file_ids' => ['a', 'b', 'c', 'd', 'e']], $a['token']);
platform_assert($many['status'] === 400, 'more than 4 saved files per message is 400');

// Rename and delete.
platform_assert(($api(['op' => 'library-rename', 'file_id' => $id1, 'name' => 'Tile quote.txt'], $a)['data']['file']['name'] ?? '') === 'Tile quote.txt', 'rename');
$del = $api(['op' => 'library-delete', 'file_id' => $id1], $a);
platform_assert($del['status'] === 200 && $del['data']['usage']['files'] === 3, 'delete');
platform_assert(count(array_filter($xlog(), fn ($l) => str_starts_with($l, 'DELETE /v1/files/file-mock-'))) === 1, 'the xAI file is deleted too');
platform_assert(!is_file($private . '/data/library/u' . $userA . '/' . $id1 . '.bin'), 'local bytes removed');
platform_assert($api(['op' => 'library-delete', 'file_id' => $id1], $a)['status'] === 404, 'deleted file is gone (404)');
fwrite(STDOUT, "library tests passed\n");
