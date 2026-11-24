<?php
declare(strict_types=1);

/*
 * A tiny remote MCP server (Streamable HTTP, JSON-RPC 2.0) for tests.
 *   /mcp       no auth
 *   /mcp-auth  needs Authorization: Bearer mcp-test-token
 * Tools: search_notes (readOnlyHint), get_note (readOnlyHint), create_note (write), delete_note (write).
 * tools/call answers as an SSE stream to exercise that path. Calls are logged to FAKE_MCP_LOG.
 */

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$log = getenv('FAKE_MCP_LOG');
$auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
if ($path === '/mcp-auth' && $auth !== 'Bearer mcp-test-token') {
    http_response_code(401);
    echo 'unauthorized';
    return;
}
if ($path !== '/mcp' && $path !== '/mcp-auth') {
    http_response_code(404);
    return;
}
$msg = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($msg)) {
    http_response_code(400);
    return;
}
$method = (string) ($msg['method'] ?? '');
if (is_string($log) && $log !== '') {
    file_put_contents($log, $method . ' ' . json_encode($msg['params'] ?? null) . ' session=' . ($_SERVER['HTTP_MCP_SESSION_ID'] ?? '') . "\n", FILE_APPEND);
}
if (!isset($msg['id'])) {
    http_response_code(202);
    return;
}
if ($method !== 'initialize' && ($_SERVER['HTTP_MCP_SESSION_ID'] ?? '') !== 'sess-123') {
    http_response_code(400);
    echo json_encode(['jsonrpc' => '2.0', 'id' => $msg['id'], 'error' => ['code' => -32000, 'message' => 'no session']]);
    return;
}
$result = match ($method) {
    'initialize' => ['protocolVersion' => '2025-06-18', 'capabilities' => ['tools' => new stdClass()], 'serverInfo' => ['name' => 'fake-notes', 'version' => '1']],
    'tools/list' => ['tools' => [
        ['name' => 'search_notes', 'description' => 'Search notes', 'inputSchema' => ['type' => 'object', 'properties' => ['q' => ['type' => 'string']]], 'annotations' => ['readOnlyHint' => true]],
        ['name' => 'get_note', 'description' => 'Read one note', 'inputSchema' => ['type' => 'object', 'properties' => ['id' => ['type' => 'string']]], 'annotations' => ['readOnlyHint' => true]],
        ['name' => 'create_note', 'description' => 'Create a note', 'inputSchema' => ['type' => 'object', 'properties' => ['title' => ['type' => 'string']], 'required' => ['title']]],
        ['name' => 'delete_note', 'description' => 'Delete a note', 'inputSchema' => ['type' => 'object', 'properties' => ['id' => ['type' => 'string']]], 'annotations' => ['readOnlyHint' => false, 'destructiveHint' => true]],
    ]],
    'tools/call' => ['content' => [['type' => 'text', 'text' => 'Created note "' . (string) ($msg['params']['arguments']['title'] ?? '') . '" as note-42']]],
    default => null,
};
if ($result === null) {
    header('Content-Type: application/json');
    echo json_encode(['jsonrpc' => '2.0', 'id' => $msg['id'], 'error' => ['code' => -32601, 'message' => 'unknown method']]);
    return;
}
if ($method === 'initialize') {
    header('Mcp-Session-Id: sess-123');
}
if ($method === 'tools/call') {
    header('Content-Type: text/event-stream');
    echo "event: message\ndata: " . json_encode(['jsonrpc' => '2.0', 'id' => $msg['id'], 'result' => $result]) . "\n\n";
    return;
}
header('Content-Type: application/json');
echo json_encode(['jsonrpc' => '2.0', 'id' => $msg['id'], 'result' => $result]);
