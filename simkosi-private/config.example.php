<?php
declare(strict_types=1);

/**
 * Copy this file to config.php in this same directory and put the real key
 * only in config.php. config.php is not part of the zip and must not be
 * committed. There is no usage cap: the site does not limit messages per
 * person or per day.
 */
return [
    'xai_api_key' => 'xai-REPLACE_ME',
    'xai_base_url' => 'https://api.x.ai/v1',
    // Current Grok chat model. Change this when you want a different one.
    'model' => 'grok-4.7',
    'stt_model' => 'grok-voice-transcribe-2.0',
    'timeout_seconds' => 45,
    // Malformed-request hygiene only. Not a usage quota.
    'max_input_chars' => 8000,
    'system_prompt' => 'You are Simko SI, Joseph Simko\'s assistant on simkosi.com. Reply in clear everyday English. Be warm, brief, and useful.',
    // dev: show confirm and reset tokens on screen (no mail server). smtp: hide them.
    'mail_mode' => 'dev',
    // Full origins allowed in addition to the request host. Leave empty on Hostinger.
    'extra_origins' => [],
    // Desktop installers. Leave empty until files exist; the site then says
    // "Desktop app download coming soon." Each url must be https.
    'installers' => [],
    // Optional. Leave enabled false. Only project wxvjajecvklfjxppawdx is honored.
    'supabase' => [
        'enabled' => false,
        'project_ref' => 'wxvjajecvklfjxppawdx',
        'url' => '',
        'service_key' => '',
    ],
];
