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
