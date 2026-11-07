# Deploy Simko SI to Hostinger

Account paths, checked on the server:

- Site root: `/home/u667559395/domains/simkosi.com/public_html`
- Private dir: `/home/u667559395/domains/simkosi.com/simkosi-private` (sibling of `public_html`, not inside it)
- Web PHP 8.3, CLI PHP 8.2. Both can run this app. `curl`, `PDO`, `pdo_sqlite`, and `sqlite3` are enabled. SSL is on.

`index.html` is listed first in `public_html/.htaccess` (`DirectoryIndex`), so it wins over Hostinger's `default.php`. Leave `default.php` where it is.

Build the zips from a checkout:

```bash
bash scripts/build.sh
```

That writes `dist/public_html.zip` and `dist/simkosi-private.zip`. The private zip has `config.example.php` only. It does not contain `config.php` or the database.

## rsync (preferred)

Use the SSH host and port from hPanel → Advanced → SSH Access. Hostinger's SSH port is usually `65002`.

```bash
HOST=your.ssh.host.from.hpanel
PORT=65002
USER=u667559395
ROOT=/home/u667559395/domains/simkosi.com

rsync -av -e "ssh -p $PORT" public_html/ \
  "$USER@$HOST:$ROOT/public_html/"

rsync -av --exclude config.php --exclude data/ -e "ssh -p $PORT" simkosi-private/ \
  "$USER@$HOST:$ROOT/simkosi-private/"
```

The public rsync does not use `--delete`, so `default.php` stays. The private rsync skips `config.php` and `data/` so a later deploy does not wipe the key or the chats.

## scp of the zips

```bash
HOST=your.ssh.host.from.hpanel
PORT=65002
USER=u667559395
ROOT=/home/u667559395/domains/simkosi.com

scp -P "$PORT" dist/public_html.zip dist/simkosi-private.zip "$USER@$HOST:$ROOT/"

ssh -p "$PORT" "$USER@$HOST" bash -s <<'EOF'
set -euo pipefail
ROOT=/home/u667559395/domains/simkosi.com
cd "$ROOT/public_html"
unzip -o "$ROOT/public_html.zip"
mkdir -p "$ROOT/simkosi-private"
cd "$ROOT/simkosi-private"
unzip -o "$ROOT/simkosi-private.zip"
mkdir -p "$ROOT/simkosi-private/data"
if [ ! -f "$ROOT/simkosi-private/config.php" ]; then
  cp "$ROOT/simkosi-private/config.example.php" "$ROOT/simkosi-private/config.php"
  chmod 600 "$ROOT/simkosi-private/config.php"
fi
EOF
```

The zip roots are the files themselves (`index.html`, `api/`, `config.example.php`), so unzip them *inside* the two target directories. Do not unzip `simkosi-private.zip` into `public_html`.

Then edit the key on the server:

```bash
ssh -p 65002 u667559395@your.ssh.host.from.hpanel
nano /home/u667559395/domains/simkosi.com/simkosi-private/config.php
```

Replace `xai-REPLACE_ME` with the real xAI key. Save. `chmod 600` that file.

Check the path PHP will use (CLI 8.2 is enough for this check):

```bash
php /home/u667559395/domains/simkosi.com/public_html/api/bootstrap.php
```

Expected:

```text
private=/home/u667559395/domains/simkosi.com/simkosi-private
config=yes
```

Open `https://simkosi.com`. Sign up, send a line, and confirm a reply.

## File Manager, if you are not using SSH

1. hPanel → Files → File Manager.
2. Go to `domains/simkosi.com/public_html`.
3. Upload `public_html.zip` and extract it here. `index.html` should sit next to `default.php`.
4. Go up to `domains/simkosi.com` (the parent of `public_html`).
5. Create `simkosi-private` if it is missing. Open it. Upload `simkosi-private.zip` and extract it here.
6. Copy `config.example.php` to `config.php` in that folder. Edit `config.php` and set `xai_api_key`. Permissions `600`.
7. Confirm `https://simkosi.com/simkosi-private/config.php` is not reachable (it must not live under `public_html`).

## Overrides

You do not need an override on this account. `public_html/api/*.php` resolves the private directory as `dirname(__DIR__, 2) . '/simkosi-private'`.

If the folder ever moves, either:

- set the environment variable `SIMKOSI_PRIVATE` (in `public_html/.htaccess`, `SetEnv SIMKOSI_PRIVATE /home/u667559395/domains/simkosi.com/simkosi-private`), or
- copy `public_html/api/private-path.example.php` to `public_html/api/private-path.php` and define the constant `SIMKOSI_PRIVATE`.

Do not put the API key in either of those.

## Local mock

```bash
npm install
npm test
```

`npm test` writes a gitignored `simkosi-private/config.php` that points at `http://127.0.0.1:8742/v1` (a fake Grok) and runs the browser test. No real key is used.

To click around locally:

```bash
bash scripts/dev.sh
```

Then open `http://127.0.0.1:8741`. Replies come from the mock until you point `xai_base_url` back at `https://api.x.ai/v1` and set a real key.

## Routines cron

Do not add this until the routines flag is meant to be on. In hPanel, Cron Jobs, every 15 minutes:

```bash
0,15,30,45 * * * * /usr/bin/php /home/u667559395/domains/simkosi.com/public_html/api/routines-worker.php
```

The worker writes the in-app note. It also emails when `mail_mode` is `smtp`.
