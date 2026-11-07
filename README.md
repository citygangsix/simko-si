# Simko SI

Phone-first website for [simkosi.com](https://simkosi.com). It is Joseph Simko's Simko SI messenger: chats on the left, the conversation on the right, a foldable layout, voice, and a lifebook. Grok (xAI) answers. The key stays in `simkosi-private`, next to `public_html`, never in this public folder and never in JavaScript.

There is no message quota. A request still has to be POST JSON from this site, and one message is limited to 8000 characters so a broken client cannot send a huge body.

## Layout

- `public_html/` is the Apache site: `index.html`, `assets/` (including the sea-turtle loop), `api/*.php`, `.htaccess`.
- `simkosi-private/` is not on the web. Copy `config.example.php` to `config.php` and set the key.
- `FEATURES.md` is the feature inventory.
- `DEPLOY.md` is the Hostinger File Manager, rsync, and scp steps.
- `bash scripts/build.sh` writes `dist/public_html.zip` and `dist/simkosi-private.zip`.

## Run locally

PHP 8.2+ with curl and pdo_sqlite:

```bash
npm install
bash scripts/dev.sh
```

The site listens on `http://127.0.0.1:8741`. A mock Grok listens on port 8742, so you can sign up and chat without a real key.

```bash
npm test
```

The test types into the chat box, checks sign-up → chat → send-to-other-chat, and checks that 40 turns in a row are accepted.
