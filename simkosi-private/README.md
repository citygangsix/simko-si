# simkosi-private

This folder sits **next to** `public_html`, not inside it.

On the Hostinger account that is:

`/home/u667559395/domains/simkosi.com/simkosi-private`

`public_html/api/chat.php` resolves it as `dirname(__DIR__, 2) . '/simkosi-private'`. Two other overrides exist if the layout ever changes: the `SIMKOSI_PRIVATE` environment variable, or a `SIMKOSI_PRIVATE` constant in `public_html/api/private-path.php` (see `private-path.example.php`).

## Key

1. Copy `config.example.php` to `config.php`.
2. Replace `xai-REPLACE_ME` with the xAI key.
3. `chmod 600 config.php`.

The key must never be committed, never be placed under `public_html`, and never be pasted into JavaScript.

`config.php` is the only required secret. SQLite (`data/simko.sqlite`) is created on the first sign-up. The `data` directory must be writable by the Hostinger account user.

## What is stored

- users, password hashes (`password_hash`), email-confirm tokens, reset tokens
- HttpOnly session cookies (the raw token is also returned to the page so the existing client can send it)
- chats and messages, scoped to the signed-in user
- Lifebook tags

There is no per-IP limit and no daily message cap.

## Email

`mail_mode` is `dev` until a mailbox is ready. `dev` shows confirm and reset codes on screen. `smtp` sends them and does not return the code. Set `smtp.host`, `smtp.port`, `smtp.user`, `smtp.password`, and `smtp.from` in `config.php` only. Port 587 uses STARTTLS. Port 465 uses SSL. The sender name is Simko SI. Each address can receive 5 of these emails an hour.

## Family

`family_ui` defaults to false, so parent and child screens stay hidden. Child profiles store a display name, a character, and an age band. They do not store a child email, birthdate, or last name. A parent has to consent, and that consent time is stored, and the parent email has to be confirmed before a child profile can be added.

## Supabase

`supabase` in the config is optional and off. If you turn it on, the only project ref the code will call is `wxvjajecvklfjxppawdx`, and only when `url` and `service_key` are both set. Chat does not wait on that call.
