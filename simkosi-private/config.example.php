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
    // Live (realtime) voice chat over xAI Speech-to-Speech, about $0.08 a minute.
    // Caps are minutes per calendar day in spend_caps.timezone (Eastern).
    // Demo accounts use the same per-person cap. The site cap is logged.
    'live_voice' => [
        'user_daily_minutes' => 10,
        'site_daily_minutes' => 60,
        'model' => 'grok-voice-latest',
        'token_ttl_seconds' => 300,
    ],
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
    // New screens stay hidden until a flag is true. All default off.
    // The message cap and paid-only images run only when platform.paywall is true.
    'platform' => [
        'paywall' => false,
        'approvals' => false,
        'search' => false,
        'memory' => false,
        'routines' => false,
        'images' => false,
        'shares' => false,
        'oauth' => false,
        'vault' => false,
        'connectors' => false,
        'agents' => false,
        'team' => false,
        'calls' => false,
        'browse' => false,
        'store' => false,
        // Code tab: owner-only coding agent (Grok engine on the xAI key; Cursor optional, dry run by default).
        'code' => false,
        // P0 (built 2026-11-24, off until Joseph turns each on): project workspaces, saved file library,
        // scheduled tasks, MCP connectors. Projects and saved files in chat need 'search' => true (Responses API).
        'projects' => false,
        'library' => false,
        'tasks' => false,
        'mcp' => false,
    ],
    // Billing. Default is Stripe. Square stays in the code as a fallback.
    // platform.paywall stays false until Joseph turns it on. Nothing is charged
    // until a person completes Stripe Checkout for the $9.99/month plan.
    // Free tier: 5 text messages, no images. Images are only on the paid plan.
    // Put the restricted key and webhook secret in this private config (or env),
    // never in git. Leave the values empty here.
    // Picture charges for subscribers: 'invoice' (one monthly invoice, default) or 'metered'
    // (one Stripe meter event per picture, billed on the $9.99 plan invoice). Env IMAGE_BILLING_MODE wins.
    'billing' => [
        'provider' => 'stripe',
        'image_billing_mode' => 'invoice',
        'image_invoice_min_cents' => 50,
    ],
    'stripe' => [
        'restricted_key' => '',
        'secret_key' => '',
        'webhook_secret' => '',
        'price_id' => '',
        // Metered mode only: a $0.01-per-unit recurring price attached to the meter below.
        'metered_price_id' => '',
        'meter_event_name' => 'simko_picture_cents',
        'api_base' => 'https://api.stripe.com',
        'api_version' => '2026-09-30.endive',
    ],
    // Square hosted checkout. Leave the access token empty. Used only if billing.provider is square.
    // Apple and Google sign-in. Leave the client ids empty until Joseph registers them.
    // Buttons stay hidden while an id is empty, and while platform.oauth is false.
    // Google: Cloud Console, OAuth client, redirect https://simkosi.com/api/oauth/callback
    // Apple: developer.apple.com, Services ID, Sign in with Apple, same redirect. $99/year membership is Joseph's decision.
    // Connectors. Client ids empty means the buttons stay hidden.
    // Google Drive uses drive.file (files the person picks). Google Calendar uses calendar.events and reuses the Drive OAuth client if its own id is empty. GitHub reads repositories. No Gmail. No banks.
    // Phone calls stay disabled. Filling a provider does not place a call and does not open an account.
    // Hosts the page reader may fetch. No logins. Full browser automation is not on shared hosting.
    'browse_allow' => [],
    'calls' => [
        'provider' => '',
        'from_number' => '',
        'enabled' => false,
    ],
    'connectors' => [
        'token_key' => '',
        'google-drive' => [
            'client_id' => '',
            'client_secret' => '',
            'authorize_url' => 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url' => 'https://oauth2.googleapis.com/token',
            'revoke_url' => 'https://oauth2.googleapis.com/revoke',
        ],
        // Leave these empty to reuse the google-drive OAuth client (same Cloud client).
        'google-calendar' => [
            'client_id' => '',
            'client_secret' => '',
            'authorize_url' => 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url' => 'https://oauth2.googleapis.com/token',
            'revoke_url' => 'https://oauth2.googleapis.com/revoke',
            'api_base' => '',
        ],
        'github' => [
            'client_id' => '',
            'client_secret' => '',
            'authorize_url' => 'https://github.com/login/oauth/authorize',
            'token_url' => 'https://github.com/login/oauth/access_token',
            'revoke_url' => '',
        ],
    ],
    'oauth' => [
        'google' => [
            'client_id' => '',
            'client_secret' => '',
            'authorize_url' => 'https://accounts.google.com/o/oauth2/v2/auth',
            'token_url' => 'https://oauth2.googleapis.com/token',
            'userinfo_url' => 'https://openidconnect.googleapis.com/v1/userinfo',
            'redirect_url' => 'https://simkosi.com/api/oauth/callback',
            'scope' => 'openid email',
        ],
        'apple' => [
            'client_id' => '',
            'team_id' => '',
            'key_id' => '',
            'p8_path' => '',
            'authorize_url' => 'https://appleid.apple.com/auth/authorize',
            'token_url' => 'https://appleid.apple.com/auth/token',
            'jwks_url' => 'https://appleid.apple.com/auth/keys',
            'redirect_url' => 'https://simkosi.com/api/oauth/callback',
            'scope' => 'name email',
        ],
    ],
    'square' => [
        'environment' => 'sandbox',
        'application_id' => '',
        'location_id' => '',
        'access_token' => '',
        'api_base' => 'https://connect.squareupsandbox.com',
    ],
    // Optional. Leave enabled false. Only project wxvjajecvklfjxppawdx is honored.
    'supabase' => [
        'enabled' => false,
        'project_ref' => 'wxvjajecvklfjxppawdx',
        'url' => '',
        'service_key' => '',
    ],
    // Paperclip: largest attachment in MB (max 20, Grok vision's limit).
    'attach_max_mb' => 8,
    // Code tab model (defaults to 'model').
    // 'code_model' => 'grok-4.7',
    // Optional Cursor Cloud Agents engine. Put the key here or in the CURSOR_API_KEY env var, never in public_html.
    // A real run uses paid Cursor time: it needs allow_launch => true AND the owner confirming each run.
    'cursor' => [
        'api_key' => '',
        'api_base' => 'https://api.cursor.com',
        'repository' => 'https://github.com/citygangsix/simko-si',
        'ref' => 'main',
        'model' => '',
        'allow_launch' => false,
    ],
    // P0 caps and settings (defaults shown).
    // Project file search uses xAI Collections, which needs a separate xAI Management API key. Never in git.
    'xai_management_key' => '',
    'xai_management_url' => 'https://management-api.x.ai/v1',
    'library' => ['max_file_mb' => 25, 'max_total_mb' => 200, 'max_files' => 200],
    'projects' => ['max_projects' => 50, 'max_files' => 20],
    'tasks' => ['max_per_user' => 5, 'run_now_per_hour' => 5, 'model' => '', 'estimate_usd' => 0.02],
    // MCP servers: only hosts on this list (plus the owner's list in the app) can be connected. https only.
    'mcp' => ['allowed_hosts' => [], 'max_servers' => 10, 'max_tools' => 50],
];
