<?php
declare(strict_types=1);

/**
 * xAI Files API and Collections (Management API) calls for the saved file library and projects.
 *
 *   Files:        POST {xai_base_url}/files (multipart, purpose=assistants)  -> {id}
 *                 DELETE {xai_base_url}/files/{id}
 *   Collections:  POST {xai_management_url}/collections {collection_name} -> {collection_id}
 *                 POST|DELETE {xai_management_url}/collections/{id}/documents/{file_id}
 *                 DELETE {xai_management_url}/collections/{id}
 *
 * The Collections calls use a separate xAI Management API key:
 *   simkosi-private/config.php: 'xai_management_key' => 'xai-...', 'xai_management_url' => 'https://management-api.x.ai/v1'
 * Every call here returns ['code' => int, 'data' => ?array, 'error' => string] and never stops the request,
 * so callers decide what the person sees. No call is made for anyone who may not use Grok (simko_api_key).
 */

function simko_xai_request(string $method, string $url, string $key, ?array $json = null, ?array $multipart = null, int $timeout = 60): array
{
    if (!function_exists('curl_init')) {
        return ['code' => 0, 'data' => null, 'error' => 'no curl'];
    }
    $ch = curl_init($url);
    if ($ch === false) {
        return ['code' => 0, 'data' => null, 'error' => 'curl init'];
    }
    $headers = ['Authorization: Bearer ' . $key, 'Accept: application/json'];
    $options = [
        CURLOPT_CUSTOMREQUEST => $method,
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => $timeout,
        CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_FOLLOWLOCATION => false,
    ];
    if ($multipart !== null) {
        $options[CURLOPT_POSTFIELDS] = $multipart;
    } elseif ($json !== null) {
        $headers[] = 'Content-Type: application/json';
        $options[CURLOPT_POSTFIELDS] = json_encode($json, JSON_UNESCAPED_UNICODE);
    } elseif ($method === 'POST') {
        $headers[] = 'Content-Type: application/json';
        $options[CURLOPT_POSTFIELDS] = '{}';
    }
    $options[CURLOPT_HTTPHEADER] = $headers;
    if (defined('CURLPROTO_HTTP') && defined('CURLPROTO_HTTPS')) {
        $options[CURLOPT_PROTOCOLS] = CURLPROTO_HTTP | CURLPROTO_HTTPS;
    }
    curl_setopt_array($ch, $options);
    $raw = curl_exec($ch);
    $error = curl_error($ch);
    $code = (int) curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    $data = is_string($raw) && $raw !== '' ? json_decode($raw, true) : [];
    if ($code === 0 || $code >= 400) {
        simko_log_upstream($code, $error !== '' ? $error : 'xai ' . $method . ' ' . (string) parse_url($url, PHP_URL_PATH));
    }
    return ['code' => $code, 'data' => is_array($data) ? $data : null, 'error' => $error];
}

function simko_xai_ok(array $res): bool
{
    return $res['code'] >= 200 && $res['code'] < 300 && is_array($res['data']);
}

function simko_xai_management_key(): string
{
    $key = trim((string) (simko_config_or_empty()['xai_management_key'] ?? ''));
    if ($key === '' || str_contains($key, 'REPLACE')) {
        $env = getenv('XAI_MANAGEMENT_KEY');
        $key = is_string($env) ? trim($env) : '';
    }
    return $key;
}

function simko_xai_management_url(string $path): string
{
    $base = rtrim((string) (simko_config_or_empty()['xai_management_url'] ?? 'https://management-api.x.ai/v1'), '/');
    return $base . '/' . ltrim($path, '/');
}

function simko_xai_collections_ready(): bool
{
    return simko_xai_management_key() !== '';
}

/** Uploads bytes to xAI Files; returns the xAI file id or '' on failure. */
function simko_xai_file_upload(string $bytes, string $name, string $mime): string
{
    $key = simko_api_key();
    $res = simko_xai_request('POST', simko_xai_url_plain('files'), $key, null, [
        'purpose' => 'assistants',
        'file' => new CURLStringFile($bytes, $name, $mime),
    ], 120);
    $id = simko_xai_ok($res) ? (string) ($res['data']['id'] ?? '') : '';
    return preg_match('/^[A-Za-z0-9_\-:.]{1,200}$/', $id) ? $id : '';
}

function simko_xai_file_delete(string $fileId): bool
{
    if ($fileId === '') {
        return true;
    }
    $res = simko_xai_request('DELETE', simko_xai_url_plain('files/' . rawurlencode($fileId)), simko_api_key());
    return ($res['code'] >= 200 && $res['code'] < 300) || $res['code'] === 404;
}

function simko_xai_collection_create(string $name): string
{
    $key = simko_xai_management_key();
    if ($key === '') {
        return '';
    }
    simko_api_key(); // same Grok access check as every other xAI call
    $res = simko_xai_request('POST', simko_xai_management_url('collections'), $key, ['collection_name' => mb_substr($name, 0, 120)]);
    $id = simko_xai_ok($res) ? (string) ($res['data']['collection_id'] ?? $res['data']['id'] ?? '') : '';
    return preg_match('/^[A-Za-z0-9_\-:.]{1,200}$/', $id) ? $id : '';
}

function simko_xai_collection_delete(string $collectionId): bool
{
    $key = simko_xai_management_key();
    if ($key === '' || $collectionId === '') {
        return false;
    }
    $res = simko_xai_request('DELETE', simko_xai_management_url('collections/' . rawurlencode($collectionId)), $key);
    return ($res['code'] >= 200 && $res['code'] < 300) || $res['code'] === 404;
}

function simko_xai_collection_add(string $collectionId, string $fileId): bool
{
    $key = simko_xai_management_key();
    if ($key === '' || $collectionId === '' || $fileId === '') {
        return false;
    }
    simko_api_key();
    $res = simko_xai_request('POST', simko_xai_management_url('collections/' . rawurlencode($collectionId) . '/documents/' . rawurlencode($fileId)), $key);
    return $res['code'] >= 200 && $res['code'] < 300;
}

function simko_xai_collection_remove(string $collectionId, string $fileId): bool
{
    $key = simko_xai_management_key();
    if ($key === '' || $collectionId === '' || $fileId === '') {
        return false;
    }
    $res = simko_xai_request('DELETE', simko_xai_management_url('collections/' . rawurlencode($collectionId) . '/documents/' . rawurlencode($fileId)), $key);
    return ($res['code'] >= 200 && $res['code'] < 300) || $res['code'] === 404;
}
