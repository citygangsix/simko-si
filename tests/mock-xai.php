<?php
declare(strict_types=1);

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';

if ($path === '/v1/chat/completions') {
    $body = json_decode(file_get_contents('php://input') ?: '', true);
    if (!is_array($body)) {
        $body = [];
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
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($payload, JSON_UNESCAPED_UNICODE);
    return;
}

if ($path === '/v1/images/generations') {
    header('Content-Type: application/json; charset=utf-8');
    $png = base64_encode(base64_decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='));
    echo json_encode(['data' => [['b64_json' => $png]]]);
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
