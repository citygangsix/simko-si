<?php
// Copy to simkosi-private/config.php (OUTSIDE public_html) and fill in real values.
// Never commit the real config.php.
return [
    'xai_api_key'      => 'REPLACE_WITH_XAI_API_KEY',
    'xai_base_url'     => 'https://api.x.ai/v1',
    'model'            => 'REPLACE_WITH_MODEL',
    'image_model'      => 'REPLACE_WITH_IMAGE_MODEL',
    'stt_model'        => 'REPLACE_WITH_STT_MODEL',
    'system_prompt'    => '',
    'max_input_chars'  => 8000,
    'timeout_seconds'  => 60,
    'stream_delay_ms'  => 0,
    'site_url'         => 'http://localhost:8000',
    'extra_origins'    => [],
    'mail_mode'        => 'log',
    'family_ui'        => false,
    'browse_allow'     => [],
    'search_blocklist' => [],
    'smtp' => ['host' => 'smtp.example.com', 'port' => 587, 'user' => 'REPLACE', 'password' => 'REPLACE', 'from' => 'noreply@example.com'],
    'supabase' => ['url' => 'https://YOUR_PROJECT_REF.supabase.co', 'anon_key' => 'REPLACE_WITH_ANON_KEY'],
    'square' => ['access_token' => 'REPLACE', 'location_id' => 'REPLACE'],
    'calls' => [],
    'oauth' => [
        // 'google' => ['client_id' => 'REPLACE', 'client_secret' => 'REPLACE', 'authorize_url' => '', 'token_url' => '',
        //              'userinfo_url' => '', 'jwks_url' => '', 'redirect_url' => '', 'scope' => ''],
        // 'apple'  => ['client_id' => 'REPLACE', 'team_id' => 'REPLACE', 'key_id' => 'REPLACE', 'p8_path' => '/path/outside/webroot/AuthKey.p8'],
    ],
    'connectors' => [],
    'platform'   => [],
    'installers' => [],
];
