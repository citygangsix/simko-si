<?php
declare(strict_types=1);

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';
$method = strtoupper((string) ($_SERVER['REQUEST_METHOD'] ?? 'GET'));
$raw = file_get_contents('php://input') ?: '';
$store = (string) getenv('SIMKO_CALENDAR_STORE');
$log = (string) getenv('SIMKO_CALENDAR_LOG');
if ($log !== '') {
    file_put_contents($log, $method . ' ' . $path . ' ' . $raw . "\n", FILE_APPEND);
}
$events = [];
if ($store !== '' && is_file($store)) {
    $decoded = json_decode((string) file_get_contents($store), true);
    $events = is_array($decoded) ? $decoded : [];
}

header('Content-Type: application/json');
$auth = (string) ($_SERVER['HTTP_AUTHORIZATION'] ?? '');
if (!str_starts_with($auth, 'Bearer ')) {
    http_response_code(401);
    echo json_encode(['error' => ['message' => 'missing token']]);
    return;
}

if ($method === 'GET' && preg_match('#/calendars/[^/]+/events/?$#', $path)) {
    echo json_encode(['items' => array_values($events)]);
    return;
}

if ($method === 'POST' && preg_match('#/calendars/[^/]+/events/?$#', $path)) {
    $body = json_decode($raw, true);
    if (!is_array($body)) {
        $body = [];
    }
    $id = 'evt-' . (count($events) + 1);
    $item = [
        'id' => $id,
        'summary' => (string) ($body['summary'] ?? ''),
        'start' => $body['start'] ?? ['dateTime' => ''],
        'end' => $body['end'] ?? ['dateTime' => ''],
        'description' => (string) ($body['description'] ?? ''),
        'location' => (string) ($body['location'] ?? ''),
        'htmlLink' => 'https://calendar.google.com/event?eid=' . $id,
    ];
    $events[$id] = $item;
    if ($store !== '') {
        file_put_contents($store, json_encode($events));
    }
    echo json_encode($item);
    return;
}

if (preg_match('#/calendars/[^/]+/events/([^/]+)$#', $path, $m)) {
    $id = urldecode($m[1]);
    if ($method === 'PATCH' || $method === 'PUT') {
        if (!isset($events[$id])) {
            http_response_code(404);
            echo json_encode(['error' => ['message' => 'not found']]);
            return;
        }
        $body = json_decode($raw, true);
        if (is_array($body)) {
            $events[$id] = array_merge($events[$id], $body);
        }
        if ($store !== '') {
            file_put_contents($store, json_encode($events));
        }
        echo json_encode($events[$id]);
        return;
    }
    if ($method === 'DELETE') {
        unset($events[$id]);
        if ($store !== '') {
            file_put_contents($store, json_encode($events));
        }
        http_response_code(204);
        return;
    }
}

http_response_code(404);
echo json_encode(['error' => ['message' => 'no ' . $method . ' ' . $path]]);
