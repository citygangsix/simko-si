<?php
declare(strict_types=1);

// Fake Google token + Drive v3 + GitHub REST for connector tool tests. Answers only to "Bearer access-one"/"access-refreshed".
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$query = [];
parse_str((string) parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_QUERY), $query);
$log = (string) getenv('SIMKO_API_LOG');
if ($log !== '') {
    file_put_contents($log, ($_SERVER['REQUEST_METHOD'] ?? 'GET') . ' ' . ($_SERVER['REQUEST_URI'] ?? '') . "\n", FILE_APPEND);
}
header('Content-Type: application/json');
$raw = file_get_contents('php://input') ?: '';
parse_str($raw, $form);
if ($path === '/token') {
    echo json_encode(($form['grant_type'] ?? '') === 'refresh_token'
        ? ['access_token' => 'access-refreshed', 'expires_in' => 3600]
        : ['access_token' => 'access-one', 'refresh_token' => 'refresh-one', 'expires_in' => 3600]);
    return true;
}
if ($path === '/revoke') {
    echo '{}';
    return true;
}
$auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
if (!in_array($auth, ['Bearer access-one', 'Bearer access-refreshed'], true)) {
    http_response_code(401);
    echo json_encode(['error' => 'bad token']);
    return true;
}
$files = [
    'doc1234567890' => ['id' => 'doc1234567890', 'name' => 'Trip plan', 'mimeType' => 'application/vnd.google-apps.document'],
    'txt1234567890' => ['id' => 'txt1234567890', 'name' => 'notes.txt', 'mimeType' => 'text/plain', 'size' => '40'],
    'png1234567890' => ['id' => 'png1234567890', 'name' => 'photo.png', 'mimeType' => 'image/png', 'size' => '400'],
];
if (preg_match('#^/drive/v3/files/([A-Za-z0-9_-]+)(/export)?$#', $path, $m)) {
    $f = $files[$m[1]] ?? null;
    if (!$f) {
        http_response_code(404);
        echo '{}';
        return true;
    }
    if (!empty($m[2])) {
        header('Content-Type: text/plain');
        echo "Trip plan: fly to Lisbon on May 3, hotel Alfama.";
        return true;
    }
    if (($query['alt'] ?? '') === 'media') {
        header('Content-Type: text/plain');
        echo "Buy dog food for Max. Call the vet Friday.";
        return true;
    }
    echo json_encode($f + ['modifiedTime' => '2026-11-20T10:00:00Z']);
    return true;
}
if ($path === '/user/repos') {
    echo json_encode([
        ['full_name' => 'citygangsix/simko-si', 'private' => true, 'description' => 'Simko SI site', 'default_branch' => 'main', 'updated_at' => '2026-11-23T00:00:00Z'],
        ['full_name' => 'citygangsix/notes', 'private' => false, 'description' => '', 'default_branch' => 'main', 'updated_at' => '2026-11-01T00:00:00Z'],
    ]);
    return true;
}
if ($path === '/repos/citygangsix/simko-si/contents/README.md') {
    echo json_encode(['type' => 'file', 'name' => 'README.md', 'content' => chunk_split(base64_encode("# Simko SI\nA calm assistant.\n"), 60, "\n")]);
    return true;
}
if ($path === '/repos/citygangsix/simko-si/contents/docs') {
    echo json_encode([['type' => 'file', 'name' => 'a.md'], ['type' => 'dir', 'name' => 'img']]);
    return true;
}
if ($path === '/repos/citygangsix/simko-si/issues') {
    echo json_encode([
        ['number' => 7, 'title' => 'Add two-step sign-in', 'user' => ['login' => 'citygangsix'], 'created_at' => '2026-11-20T00:00:00Z'],
        ['number' => 8, 'title' => 'A pull request', 'pull_request' => ['url' => 'x'], 'user' => ['login' => 'bot'], 'created_at' => '2026-11-21T00:00:00Z'],
    ]);
    return true;
}
http_response_code(404);
echo json_encode(['message' => 'Not Found']);
return true;
