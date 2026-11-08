# Simko SI

- `app/` — the Simko SI local desktop app (local platform server, chat UI, Tauri desktop wrapper, tests).
- `website/` — the simkosi.com site (PHP + static front end), matching what is live.

No secrets are in this repo. Copy the `*.example` files and fill in your own values.

## Run the local app on Windows (Acer Aspire)

### Requirements
- Windows 10/11, 8 GB RAM minimum (16 GB+ for local AI models)
- [Git for Windows](https://git-scm.com/download/win) (includes Git Bash)
- [Python 3.11 or 3.12](https://www.python.org/downloads/windows/) — tick "Add python.exe to PATH"
- Optional: [Node.js 20 LTS](https://nodejs.org/) (web UI build / desktop wrapper), [Ollama](https://ollama.com/download/windows) (local AI)

### Install (PowerShell)
```powershell
git clone https://github.com/citygangsix/simko-si.git
cd simko-si\app
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1          # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r podcoder-translator-renter\requirements-desktop.txt pytest
copy podcoder-translator-renter\local\.env.example podcoder-translator-renter\local\.env
notepad podcoder-translator-renter\local\.env   # fill in only the keys you use
```

### Start
```powershell
cd podcoder-translator-renter\local
python server.py
```
Then open http://127.0.0.1:8788/ in your browser.
(In Git Bash you can instead run `bash start_local.sh`, which also loads `.env`.)

### Run the tests
```powershell
cd simko-si\app
python -m pytest -q podcoder-translator-renter\podcoder
```

### Optional: web front end
```powershell
cd simko-si\app
copy .env.example .env
npm install
npm run dev
```

## Website (`website/`)
PHP 8.x site. For a local try-out:
```powershell
cd simko-si\website
php -S localhost:8000 router.php
```
Real keys go in `simkosi-private/config.php` **outside** the web root
(see `website/config.example.php` and `website/api/private-path.example.php`). Never commit it.
