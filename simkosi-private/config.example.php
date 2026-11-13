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
    ],
    // Billing. Default is Stripe. Square stays in the code as a fallback.
    // platform.paywall stays false until Joseph turns it on. Nothing is charged
    // until a person completes Stripe Checkout for the $9.99/month plan.
    // Free tier: 5 text messages, no images. Images are only on the paid plan.
    // Put the restricted key and webhook secret in this private config (or env),
    // never in git. Leave the values empty here.
    'billing' => [
        'provider' => 'stripe',
    ],
    'stripe' => [
        'restricted_key' => '',
        'secret_key' => '',
        'webhook_secret' => '',
        'price_id' => '',
        'api_base' => 'https://api.stripe.com',
        'api_version' => '2026-09-30.endive',
    ],
    // Square hosted checkout. Leave the access token empty. Used only if billing.provider is square.
    // Apple and Google sign-in. Leave the client ids empty until Joseph registers them.
    // Buttons stay hidden while an id is empty, and while platform.oauth is false.
    // Google: Cloud Console, OAuth client, redirect https://simkosi.com/api/oauth/callback
    // Apple: developer.apple.com, Services ID, Sign in with Apple, same redirect. $99/year membership is Joseph's decision.
    // Connectors. Client ids empty means the buttons stay hidden.
    // Google Drive is read-only. GitHub reads repositories. No Gmail. No banks.
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
];
