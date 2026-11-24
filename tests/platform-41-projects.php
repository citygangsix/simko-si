<?php
declare(strict_types=1);

require __DIR__ . '/platform-support.php';

// P0 project workspaces: instructions in chat, files in a (mock) xAI Collection searched with file_search,
// chats in a project, owner-only, caps, cleanup of the collection.
$site = 9142;
$mockPort = 9143;
platform_require_free_port($site);
platform_require_free_port($mockPort);
$log = sys_get_temp_dir() . '/simko-p0proj-' . getmypid() . '.log';
@unlink($log);
putenv('MOCK_XAI_P0_LOG=' . $log);
platform_mock($mockPort);
$private = platform_private('p0proj', ['projects' => true, 'library' => true, 'search' => true, 'paywall' => false], [
    'xai_base_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'xai_management_key' => 'xai-mgmt-mock',
    'xai_management_url' => 'http://127.0.0.1:' . $mockPort . '/v1',
    'projects' => ['max_projects' => 2, 'max_files' => 2],
]);
[$proc, $pipes] = platform_site($private, $site);
$a = platform_signup($site, 'proja-' . getmypid() . '@simkosi.test');
$b = platform_signup($site, 'projb-' . getmypid() . '@simkosi.test');
$api = static fn (array $body, array $who) => platform_api($site, '/api/platform', $body, $who['token']);
$xlog = static fn (): array => file_exists($log) ? (file($log, FILE_IGNORE_NEW_LINES) ?: []) : [];
$save = static fn (array $who, string $name, string $body) => $api(['op' => 'library-save', 'name' => $name, 'data' => base64_encode($body)], $who)['data']['file']['id'] ?? '';

platform_assert(platform_api($site, '/api/platform', ['op' => 'project-list'])['status'] === 401, 'signed-out project-list is 401');
$p = $api(['op' => 'project-save', 'name' => 'Kitchen remodel', 'instructions' => 'Budget is $18k. Keep answers short.'], $a);
platform_assert($p['status'] === 200 && ($p['data']['project']['name'] ?? '') === 'Kitchen remodel', 'project created');
$pid = (int) $p['data']['project']['id'];
platform_assert($api(['op' => 'project-save', 'name' => ''], $a)['status'] === 400, 'a project needs a name');
platform_assert($api(['op' => 'project-save', 'name' => 'x', 'instructions' => str_repeat('i', 4001)], $a)['status'] === 400, 'instructions over 4000 chars are refused');
platform_assert(count($api(['op' => 'project-list'], $a)['data']['projects']) === 1, 'project listed');

// Owner-only.
platform_assert($api(['op' => 'project-list'], $b)['data']['projects'] === [], 'another account sees no projects');
platform_assert($api(['op' => 'project-get', 'project_id' => $pid], $b)['status'] === 404, 'another account cannot read the project (404)');
platform_assert($api(['op' => 'project-save', 'id' => $pid, 'name' => 'mine now'], $b)['status'] === 404, 'another account cannot edit the project (404)');
platform_assert($api(['op' => 'project-delete', 'project_id' => $pid], $b)['status'] === 404, 'another account cannot delete the project (404)');
$bt = platform_api($site, '/api/simco/turn', ['text' => 'hi', 'project_id' => $pid], $b['token']);
platform_assert($bt['status'] === 404, 'another account cannot chat inside the project (404)');

// Project cap.
platform_assert($api(['op' => 'project-save', 'name' => 'Taxes'], $a)['status'] === 200, 'second project');
$cap = $api(['op' => 'project-save', 'name' => 'Third'], $a);
platform_assert($cap['status'] === 409 && ($cap['data']['cap'] ?? '') === 'projects', 'project cap is 409');

// Files -> collection.
$f1 = $save($a, 'quote.txt', 'Tile quote 1840 dollars');
$f2 = $save($a, 'layout.txt', 'Island 4ft by 7ft');
$f3 = $save($a, 'permit.txt', 'Permit number 22-118');
$fb = $save($b, 'b.txt', 'other person file');
platform_assert($f1 !== '' && $fb !== '', 'library files saved');
platform_assert($api(['op' => 'project-file-add', 'project_id' => $pid, 'file_id' => $fb], $a)['status'] === 404, 'cannot add another account\'s file (404)');
platform_assert($api(['op' => 'project-file-add', 'project_id' => $pid, 'file_id' => $fb], $b)['status'] === 404, 'another account cannot add to the project (404)');
$add = $api(['op' => 'project-file-add', 'project_id' => $pid, 'file_id' => $f1], $a);
platform_assert($add['status'] === 200 && $add['data']['project']['search_ready'] === true && count($add['data']['project']['files']) === 1, 'file added; collection ready');
$lines = $xlog();
platform_assert(in_array('POST /v1/collections', $lines, true) && count(array_filter($lines, fn ($l) => preg_match('#^POST /v1/collections/collection_mock_\w+/documents/file-mock-#', $l))) === 1, 'collection created (management key) and document added');
platform_assert($api(['op' => 'project-file-add', 'project_id' => $pid, 'file_id' => $f2], $a)['status'] === 200, 'second file added');
$cap = $api(['op' => 'project-file-add', 'project_id' => $pid, 'file_id' => $f3], $a);
platform_assert($cap['status'] === 409 && ($cap['data']['cap'] ?? '') === 'project_files', 'project file cap is 409');
platform_assert(count(array_filter($xlog(), fn ($l) => $l === 'POST /v1/collections')) === 1, 'one collection per project');

// Chat inside the project.
$t = platform_api($site, '/api/simco/turn', ['text' => 'What did the tile quote say?', 'project_id' => $pid], $a['token']);
$reply = (string) ($t['data']['everyday'] ?? '');
platform_assert($t['status'] === 200 && str_contains($reply, '[file_search:collection_mock_') && str_contains($reply, '[instructions:Budget is $18k'), 'chat uses project instructions and file_search: ' . $reply);
$plain = platform_api($site, '/api/simco/turn', ['text' => 'hello'], $a['token']);
platform_assert(!str_contains((string) ($plain['data']['everyday'] ?? ''), 'file_search'), 'a chat outside the project gets no file_search');

// Chats in projects.
$chat = platform_api($site, '/api/sessions', ['op' => 'create', 'title' => 'Tile'], $a['token'])['data']['session']['id'] ?? '';
$chatB = platform_api($site, '/api/sessions', ['op' => 'create', 'title' => 'B chat'], $b['token'])['data']['session']['id'] ?? '';
platform_assert($api(['op' => 'project-chat-assign', 'chat_id' => $chat, 'project_id' => $pid], $b)['status'] === 404, 'another account cannot move the chat (404)');
platform_assert($api(['op' => 'project-chat-assign', 'chat_id' => $chatB, 'project_id' => $pid], $a)['status'] === 404, 'cannot move another account\'s chat (404)');
platform_assert($api(['op' => 'project-chat-assign', 'chat_id' => $chatB, 'project_id' => $pid], $b)['status'] === 404, 'cannot move a chat into another account\'s project (404)');
platform_assert($api(['op' => 'project-chat-assign', 'chat_id' => $chat, 'project_id' => $pid], $a)['status'] === 200, 'chat moved into the project');
$got = $api(['op' => 'project-get', 'project_id' => $pid], $a)['data']['project'];
platform_assert(count($got['chats']) === 1 && $got['chats'][0]['id'] === $chat && $got['file_count'] === 2, 'project shows its chat and files');

// Remove a file, delete a library file that is in the project, delete the project.
platform_assert(count($api(['op' => 'project-file-remove', 'project_id' => $pid, 'file_id' => $f1], $a)['data']['project']['files']) === 1, 'file removed from the project');
platform_assert(count(array_filter($xlog(), fn ($l) => str_starts_with($l, 'DELETE /v1/collections/') && str_contains($l, '/documents/'))) === 1, 'document removed from the collection');
$api(['op' => 'library-delete', 'file_id' => $f2], $a);
platform_assert($api(['op' => 'project-get', 'project_id' => $pid], $a)['data']['project']['file_count'] === 0, 'deleting a library file takes it out of the project');
$del = $api(['op' => 'project-delete', 'project_id' => $pid], $a);
platform_assert($del['status'] === 200 && count(array_filter($xlog(), fn ($l) => preg_match('#^DELETE /v1/collections/collection_mock_\w+$#', $l))) === 1, 'project deleted with its collection');
$db = new PDO('sqlite:' . $private . '/data/simko.sqlite');
$st = $db->prepare('SELECT project_id FROM chats WHERE id = ?');
$st->execute([$chat]);
platform_assert($st->fetchColumn() === null, 'its chats stay, outside any project');
platform_assert($api(['op' => 'project-get', 'project_id' => $pid], $a)['status'] === 404, 'deleted project is gone (404)');
fwrite(STDOUT, "projects tests passed\n");
