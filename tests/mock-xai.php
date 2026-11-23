<?php
declare(strict_types=1);

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$callLog = getenv('MOCK_XAI_LOG');
if (is_string($callLog) && $callLog !== '') {
    file_put_contents($callLog, $path . "\n", FILE_APPEND);
}
$bodyLog = getenv('MOCK_XAI_BODIES');
if (is_string($bodyLog) && $bodyLog !== '') {
    file_put_contents($bodyLog, (string) file_get_contents('php://input') . "\n", FILE_APPEND);
}

// Mock Cursor Cloud Agents API (tests point cursor.api_base here).
if ($path === '/v1/me' || str_starts_with($path, '/v1/agents')) {
    header('Content-Type: application/json');
    $auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
    if ($auth !== 'Bearer cursor-mock-key') {
        http_response_code(401);
        echo json_encode(['error' => 'bad key']);
        return;
    }
    if ($path === '/v1/me') {
        echo json_encode(['apiKeyName' => 'mock key', 'userEmail' => 'mock@cursor.test']);
    } elseif ($path === '/v1/agents' && ($_SERVER['REQUEST_METHOD'] ?? '') === 'POST') {
        echo json_encode(['agent' => ['id' => 'bc-mock-1'], 'run' => ['id' => 'run-1', 'status' => 'CREATING']]);
    } else {
        echo json_encode(['id' => 'bc-mock-1', 'status' => 'FINISHED', 'summary' => 'Mock agent finished.']);
    }
    return;
}

if ($path === '/v1/chat/completions') {
    $body = json_decode(file_get_contents('php://input') ?: '', true);
    if (!is_array($body)) {
        $body = [];
    }
    if (($body['response_format']['json_schema']['name'] ?? '') === 'simko_code_project') {
        // Mock Grok coding agent: a calculator. "BROKEN" in the request makes the first build concatenate.
        $all = json_encode($body['messages'] ?? []);
        if (str_contains($all, 'XAIDOWN')) {
            http_response_code(503);
            header('Content-Type: application/json');
            echo json_encode(['error' => 'mock outage']);
            return;
        }
        if (str_contains($all, 'SLOWBUILD')) {
            sleep(6);
        }
        $isFix = str_contains($all, 'failed in a browser sandbox') || str_contains($all, 'run in a browser sandbox and failed');
        $broken = str_contains($all, 'BROKEN') && !$isFix;
        $js = "var shown='';var a=null;var op=null;\nfunction paint(){document.getElementById('display').textContent=shown===''?'0':shown;}\n"
            . "document.querySelectorAll('[data-d]').forEach(function(b){b.addEventListener('click',function(){shown+=b.dataset.d;paint();});});\n"
            . "document.getElementById('plus').addEventListener('click',function(){a=shown;op='+';shown='';paint();});\n"
            . "document.getElementById('equals').addEventListener('click',function(){if(op==='+'){shown=String(" . ($broken ? "a+shown" : "Number(a)+Number(shown)") . ");op=null;}paint();});\n"
            . "document.getElementById('clear').addEventListener('click',function(){shown='';a=null;op=null;paint();});paint();";
        $digits = '';
        for ($d = 0; $d <= 9; $d++) {
            $digits .= '<button id="btn' . $d . '" data-d="' . $d . '">' . $d . '</button>';
        }
        $project = [
            'title' => 'Calculator',
            'summary' => 'A small calculator page.',
            'plan' => ['Lay out a display and buttons', 'Wire digits and plus', 'Compute on equals', 'Test 4 + 4 = 8'],
            'entry' => 'index.html',
            'files' => [
                ['path' => 'index.html', 'content' => '<!doctype html><html><head><title>Calculator</title><link rel="stylesheet" href="style.css"></head><body><div id="display">0</div>' . $digits . '<button id="plus">+</button><button id="equals">=</button><button id="clear">C</button><script src="app.js"></script></body></html>'],
                ['path' => 'style.css', 'content' => 'body{font-family:sans-serif}#display{font-size:2rem;padding:8px;border:1px solid #999;margin-bottom:8px}button{font-size:1.2rem;margin:2px;min-width:44px}'],
                ['path' => 'app.js', 'content' => $js],
            ],
            'tests' => [
                ['name' => '4 + 4 = 8', 'steps' => [
                    ['action' => 'click', 'selector' => '#btn4', 'value' => ''],
                    ['action' => 'click', 'selector' => '#plus', 'value' => ''],
                    ['action' => 'click', 'selector' => '#btn4', 'value' => ''],
                    ['action' => 'click', 'selector' => '#equals', 'value' => ''],
                    ['action' => 'expect_text', 'selector' => '#display', 'value' => '8'],
                ]],
            ],
        ];
        if (str_contains($all, 'EVILPATH')) {
            $project['files'][] = ['path' => '../../escape.php', 'content' => '<?php echo 1;'];
            $project['files'][0]['content'] = str_replace('</head>', '<script src="https://cdn.example.com/x.js"></script></head>', $project['files'][0]['content']);
        }
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['id' => 'mock-code', 'model' => $body['model'] ?? 'grok-4.7',
            'choices' => [['message' => ['role' => 'assistant', 'content' => json_encode($project)]]],
            'usage' => ['prompt_tokens' => 900, 'completion_tokens' => 1200, 'cost_in_usd_ticks' => 80000000]]);
        return;
    }
    $text = '';
    foreach ($body['messages'] ?? [] as $message) {
        if (!is_array($message) || ($message['role'] ?? '') !== 'user') {
            continue;
        }
        $content = $message['content'] ?? '';
        $text = is_string($content) ? $content : json_encode($content);
    }
    $system = '';
    foreach ($body['messages'] ?? [] as $message) {
        if (is_array($message) && ($message['role'] ?? '') === 'system') {
            $system = (string) ($message['content'] ?? '');
        }
    }
    $text = trim((string) preg_replace('/\s+/', ' ', $text));
    if (str_contains($system, 'asked you to remember')) {
        $text .= ' [remembered]';
    }
    if (!empty($body['stream'])) {
        header('Content-Type: text/event-stream; charset=utf-8');
        $delay = (int) ($body['stream_delay_ms'] ?? 0);
        $persona = '';
        if (preg_match('/You are ([^.]+)\./', $system, $match)) {
            $persona = $match[1];
        }
        $parts = [$persona . ':', $text];
        foreach ($parts as $part) {
            if ($delay > 0) {
                usleep($delay * 1000);
            }
            echo 'data: ' . json_encode(['choices' => [['delta' => ['content' => $part]]]]) . "\n\n";
            flush();
        }
        echo "data: [DONE]\n\n";
        return;
    }
    $payload = [
        'id' => 'mock-completion',
        'model' => $body['model'] ?? 'grok-4.7',
        'choices' => [[
            'message' => [
                'role' => 'assistant',
                'content' => 'The reef heard you: ' . $text,
            ],
        ]],
    ];
    if (!empty($body['search_parameters'])) {
        $payload['citations'] = [
            'https://example.com/reef',
            'https://evil.example/casino-tips',
        ];
    }
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    return;
}

if ($path === '/v1/responses') {
    $body = json_decode(file_get_contents('php://input') ?: '', true);
    if (!is_array($body)) {
        $body = [];
    }
    $text = '';
    $system = '';
    foreach ($body['input'] ?? [] as $message) {
        if (!is_array($message)) {
            continue;
        }
        $content = $message['content'] ?? '';
        $flat = is_string($content) ? $content : json_encode($content);
        if (($message['role'] ?? '') === 'system') {
            $system = (string) $flat;
        }
        if (($message['role'] ?? '') === 'user') {
            $text = $flat;
        }
    }
    $text = trim((string) preg_replace('/\s+/', ' ', $text));
    if (str_contains($system, 'asked you to remember')) {
        $text .= ' [remembered]';
    }
    $reply = 'The reef heard you: ' . $text;
    if (str_contains($text, 'input_image') && str_contains($text, 'data:image')) {
        $reply = 'The reef saw a picture. ' . $reply;
        $text = preg_replace('#data:image\\\\?/[a-z]+;base64,[A-Za-z0-9+/=\\\\]+#', 'IMG', $text) ?? $text;
        $reply = 'The reef saw a picture: ' . $text;
    }
    if (str_contains($system, 'DeepSearch mode')) {
        $reply = '[deep] ' . $reply;
    }
    if (str_contains($text, 'ECHOTOOLS')) {
        $types = [];
        foreach ($body['tools'] ?? [] as $tool) {
            $types[] = is_array($tool) ? (string) ($tool['type'] ?? '') : '';
        }
        $reply .= ' [tools:' . implode(',', $types) . '] [effort:' . (string) ($body['reasoning']['effort'] ?? 'none') . ']';
    }
    $payload = [
        'id' => 'mock-response',
        'object' => 'response',
        'model' => $body['model'] ?? 'grok-4.7',
        'status' => 'completed',
        'output_text' => $reply,
        'output' => [[
            'type' => 'message',
            'role' => 'assistant',
            'status' => 'completed',
            'content' => [[
                'type' => 'output_text',
                'text' => $reply,
            ]],
        ]],
    ];
    foreach ($body['tools'] ?? [] as $tool) {
        if (is_array($tool) && ($tool['type'] ?? '') === 'code_interpreter' && str_contains($text, 'ECHOTOOLS')) {
            array_unshift($payload['output'], [
                'type' => 'code_interpreter_call',
                'status' => 'completed',
                'code' => 'print(6 * 7)',
                'outputs' => [['type' => 'logs', 'logs' => '{"stdout":"42\\n","stderr":"","exit_code":0}']],
            ]);
        }
    }
    $payload['usage'] = ['input_tokens' => 10, 'output_tokens' => 5, 'cost_in_usd_ticks' => 1234567];
    if (str_contains($system, 'DeepSearch mode')) {
        array_unshift($payload['output'], ['type' => 'x_search_call', 'status' => 'completed', 'action' => ['sources' => [['url' => 'https://x.com/i/status/1']]]]);
        array_unshift($payload['output'], ['type' => 'web_search_call', 'status' => 'completed', 'action' => ['sources' => [['url' => 'https://example.com/second']]]]);
    }
    $hasSearch = false;
    foreach ($body['tools'] ?? [] as $tool) {
        if (is_array($tool) && ($tool['type'] ?? '') === 'web_search') {
            $hasSearch = true;
            break;
        }
    }
    if ($hasSearch) {
        $payload['citations'] = [
            'https://example.com/reef',
            'https://evil.example/casino-tips',
        ];
        $payload['output'] = array_merge([[
            'type' => 'web_search_call',
            'status' => 'completed',
            'action' => [
                'sources' => [
                    ['url' => 'https://example.com/reef'],
                    ['url' => 'https://evil.example/casino-tips'],
                ],
            ],
        ]], $payload['output']);
    }
    if (!empty($body['stream'])) {
        header('Content-Type: text/event-stream; charset=utf-8');
        $persona = '';
        if (preg_match('/You are ([^.]+)\./', $system, $match)) {
            $persona = $match[1];
        }
        $delay = (int) ($body['stream_delay_ms'] ?? 0);
        foreach ([$persona . ':', $reply] as $part) {
            if ($delay > 0) {
                usleep($delay * 1000);
            }
            echo "event: response.output_text.delta\n";
            echo 'data: ' . json_encode(['type' => 'response.output_text.delta', 'delta' => $part]) . "\n\n";
            flush();
        }
        echo "event: response.completed\n";
        echo 'data: ' . json_encode(['type' => 'response.completed', 'response' => $payload]) . "\n\n";
        return;
    }
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    return;
}

if ($path === '/v1/images/generations') {
    header('Content-Type: application/json; charset=utf-8');
    $png = base64_encode(base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='));
    $imgBody = json_decode(file_get_contents('php://input') ?: '', true);
    $out = ['data' => [['b64_json' => $png]]];
    if (!str_contains((string) ($imgBody['prompt'] ?? ''), 'NOCOST')) {
        $out['usage'] = ['cost_in_usd_ticks' => 400000000];
    }
    echo json_encode($out);
    return;
}

if ($path === '/v1/tts') {
    header('Content-Type: audio/wav');
    header('Cache-Control: no-store');
    echo simko_mock_wav();
    return;
}

if ($path === '/v1/stt') {
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode(['text' => 'mock transcript', 'language' => 'en']);
    return;
}

http_response_code(404);
header('Content-Type: application/json; charset=utf-8');
echo json_encode(['error' => 'mock has no ' . $path]);

function simko_mock_wav(): string
{
    $rate = 8000;
    $samples = 1600;
    $pcm = str_repeat("\0\0", $samples);
    $dataBytes = strlen($pcm);
    return 'RIFF' . pack('V', 36 + $dataBytes) . 'WAVE'
        . 'fmt ' . pack('VvvVVvv', 16, 1, 1, $rate, $rate * 2, 2, 16)
        . 'data' . pack('V', $dataBytes) . $pcm;
}
