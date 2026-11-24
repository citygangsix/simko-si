<?php
declare(strict_types=1);

/*
 * Mock xAI for the P0 features (included by mock-xai.php; no live xAI call is ever made in tests):
 *   Files API         POST /v1/files (multipart), DELETE /v1/files/{id}
 *   Collections       /v1/collections... (Management API; needs Bearer xai-mgmt-mock)
 *   Responses         file_search / mcp tools, input_file parts, mcp_* function tools.
 * Returns true when it answered the request.
 */

function simko_mock_p0(string $path): bool
{
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    $log = getenv('MOCK_XAI_P0_LOG');
    $auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
    $note = static function (string $line) use ($log): void {
        if (is_string($log) && $log !== '') {
            file_put_contents($log, $line . "\n", FILE_APPEND);
        }
    };
    if ($path === '/v1/files' && $method === 'POST') {
        header('Content-Type: application/json');
        $file = $_FILES['file'] ?? null;
        if (!is_array($file) || ($_POST['purpose'] ?? '') !== 'assistants' || $auth !== 'Bearer xai-local-mock') {
            http_response_code(400);
            echo json_encode(['error' => 'bad upload']);
            return true;
        }
        $id = 'file-mock-' . substr(sha1((string) file_get_contents($file['tmp_name'])), 0, 12);
        $note('POST /v1/files ' . $id . ' ' . $file['name'] . ' ' . $file['size']);
        echo json_encode(['id' => $id, 'object' => 'file', 'bytes' => (int) $file['size'], 'filename' => $file['name']]);
        return true;
    }
    if (preg_match('#^/v1/files/([^/]+)$#', $path, $m) && $method === 'DELETE') {
        $note('DELETE /v1/files/' . $m[1]);
        header('Content-Type: application/json');
        echo json_encode(['id' => $m[1], 'deleted' => true]);
        return true;
    }
    if (str_starts_with($path, '/v1/collections')) {
        header('Content-Type: application/json');
        if ($auth !== 'Bearer xai-mgmt-mock') {
            http_response_code(401);
            echo json_encode(['error' => 'management key needed']);
            return true;
        }
        $note($method . ' ' . $path);
        if ($path === '/v1/collections' && $method === 'POST') {
            $b = json_decode((string) file_get_contents('php://input'), true);
            echo json_encode(['collection_id' => 'collection_mock_' . substr(sha1((string) ($b['collection_name'] ?? '')), 0, 10), 'collection_name' => $b['collection_name'] ?? '']);
            return true;
        }
        echo json_encode(new stdClass());
        return true;
    }
    if ($path !== '/v1/responses') {
        return false;
    }
    $raw = (string) file_get_contents('php://input');
    $body = json_decode($raw, true);
    if (!is_array($body)) {
        return false;
    }
    $fileSearch = [];
    $mcp = [];
    $mcpFns = [];
    $siteFns = [];
    foreach ((array) ($body['tools'] ?? []) as $t) {
        if (!is_array($t)) {
            continue;
        }
        if (($t['type'] ?? '') === 'file_search') {
            $fileSearch = array_merge($fileSearch, (array) ($t['vector_store_ids'] ?? []));
        } elseif (($t['type'] ?? '') === 'mcp') {
            $mcp[] = $t['server_label'] . '=' . implode('|', (array) ($t['allowed_tools'] ?? [])) . (isset($t['headers']['Authorization']) ? '+auth' : '');
        } elseif (($t['type'] ?? '') === 'function' && str_starts_with((string) ($t['name'] ?? ''), 'mcp_')) {
            $mcpFns[] = (string) $t['name'];
        } elseif (($t['type'] ?? '') === 'function' && in_array((string) ($t['name'] ?? ''), ['create_task', 'turn_paywall_on'], true)) {
            $siteFns[] = (string) $t['name'];
        }
    }
    $fileIds = [];
    preg_match_all('/"type":"input_(?:file|image)","file_id":"([^"]+)"/', $raw, $fm);
    $fileIds = $fm[1] ?? [];
    $text = '';
    $system = '';
    $fnOutput = null;
    foreach ((array) ($body['input'] ?? []) as $msg) {
        if (!is_array($msg)) {
            continue;
        }
        if (($msg['type'] ?? '') === 'function_call_output') {
            $fnOutput = (string) ($msg['output'] ?? '');
        }
        $c = $msg['content'] ?? '';
        $flat = is_string($c) ? $c : json_encode($c);
        if (($msg['role'] ?? '') === 'user') {
            $text = (string) $flat;
        }
        if (($msg['role'] ?? '') === 'system') {
            $system = (string) $flat;
        }
    }
    $project = str_contains($system, 'inside the person\'s project') || str_contains($system, 'Connector action result')
        || str_contains($system, 'Scheduled task result:') || str_contains($system, 'Paywall result:') || str_contains($system, 'Connector consent:')
        || str_contains($system, 'tapped No on these');
    if ($fileSearch === [] && $mcp === [] && $mcpFns === [] && $siteFns === [] && $fileIds === [] && !$project) {
        return false;
    }
    $output = [];
    $pickFn = static function (array $fns, string $want): string {
        foreach ($fns as $f) {
            if (str_contains($f, $want)) {
                return $f;
            }
        }
        return $fns[0];
    };
    if ($mcpFns !== [] && $fnOutput === null && str_contains($text, 'MCPWRITE')) {
        $output[] = ['type' => 'function_call', 'call_id' => 'call_mcp_1', 'name' => $pickFn($mcpFns, 'create_note'), 'arguments' => json_encode(['title' => 'Buy grout'])];
        $reply = '';
    } elseif ($mcpFns !== [] && $fnOutput === null && str_contains($text, 'MCPREAD')) {
        $output[] = ['type' => 'function_call', 'call_id' => 'call_mcp_2', 'name' => $pickFn($mcpFns, 'search_notes'), 'arguments' => json_encode(['query' => 'grout'])];
        $reply = '';
    } elseif (in_array('create_task', $siteFns, true) && $fnOutput === null && str_contains($text, 'TASKCREATE')) {
        $output[] = ['type' => 'function_call', 'call_id' => 'call_task_1', 'name' => 'create_task', 'arguments' => json_encode([
            'name' => 'Morning news', 'prompt' => 'Give me three top headlines in plain words.', 'freq' => 'daily', 'hour' => 7, 'minute' => 15,
        ])];
        $reply = '';
    } elseif (in_array('turn_paywall_on', $siteFns, true) && $fnOutput === null && str_contains($text, 'PAYWALLON')) {
        $output[] = ['type' => 'function_call', 'call_id' => 'call_pay_1', 'name' => 'turn_paywall_on', 'arguments' => '{}'];
        $reply = '';
    } else {
        $bits = [];
        if ($fileSearch !== []) {
            $bits[] = '[file_search:' . implode(',', $fileSearch) . ']';
            $output[] = ['type' => 'file_search_call', 'status' => 'completed', 'queries' => ['q']];
        }
        if ($mcp !== []) {
            $bits[] = '[mcp:' . implode(';', $mcp) . ']';
        }
        if ($fileIds !== []) {
            $bits[] = '[files:' . implode(',', $fileIds) . ']';
        }
        if (preg_match('/Project instructions from the person[^\n]*\n([^\n]{0,60})/', $system, $pm)) {
            $bits[] = '[instructions:' . trim($pm[1]) . ']';
        }
        if (preg_match('/Connector action result: (.{0,160})/s', $system, $cm)) {
            $bits[] = '[connector:' . preg_replace('/\s+/', ' ', $cm[1]) . ']';
        }
        foreach (['Scheduled task result' => 'task', 'Paywall result' => 'paywall', 'Connector consent' => 'consent'] as $needle => $tag) {
            if (preg_match('/' . $needle . ': (.{0,160})/s', $system, $xm)) {
                $bits[] = '[' . $tag . ':' . preg_replace('/\s+/', ' ', $xm[1]) . ']';
            }
        }
        if (str_contains($system, 'tapped No on these')) {
            $bits[] = '[declined-noted]';
        }
        $reply = 'The reef heard you. ' . implode(' ', $bits);
    }
    $output[] = ['type' => 'message', 'role' => 'assistant', 'status' => 'completed', 'content' => [['type' => 'output_text', 'text' => $reply]]];
    $payload = ['id' => 'mock-p0', 'object' => 'response', 'model' => $body['model'] ?? 'grok-4.7', 'status' => 'completed',
        'output_text' => $reply, 'output' => $output, 'usage' => ['input_tokens' => 10, 'output_tokens' => 5, 'cost_in_usd_ticks' => 1234567]];
    if (!empty($body['stream'])) {
        header('Content-Type: text/event-stream; charset=utf-8');
        echo "event: response.output_text.delta\n";
        echo 'data: ' . json_encode(['type' => 'response.output_text.delta', 'delta' => $reply]) . "\n\n";
        echo "event: response.completed\n";
        echo 'data: ' . json_encode(['type' => 'response.completed', 'response' => $payload]) . "\n\n";
        return true;
    }
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    return true;
}
