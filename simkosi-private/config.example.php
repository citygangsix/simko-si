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
    // dev: show confirm and reset codes on screen (no mail server). Tests use this.
    // smtp: send those emails and do not return the code to the browser.
    'mail_mode' => 'dev',
    // Public site used inside confirmation and reset links.
    'site_url' => 'https://simkosi.com',
    // Parent and child screens stay hidden until this is true. Default off.
    'family_ui' => false,
    // Used only when mail_mode is smtp. Password stays in config.php, never in git.
    // port 587 uses STARTTLS. port 465 uses SSL. from_name is sent as Simko SI.
    'smtp' => [
        'host' => 'smtp.example.com',
        'port' => 587,
        'encryption' => 'starttls',
        'user' => 'mailer@simkosi.com',
        'password' => 'REPLACE_ME',
        'from' => 'hello@simkosi.com',
        'from_name' => 'Simko SI',
        'verify_peer' => true,
    ],
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
