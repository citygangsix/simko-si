# podcoder-translator-renter
Local workbench first. Confirm-gated rent only — no live rent without the human word `RENT`.

Each rent is one computer and one stack. A coding computer gets Ollama + Granite + Aider only. A media computer gets ComfyUI only, plus Wan 2.2 5B when you choose it. ComfyUI is not installed on the coding computer. Putting both on one machine is optional later, not the default.

This is not a pod-only boot kit. The pack does not rent or destroy Vast instances. Joseph shut Utah **58092881** on 2026-10-28 (~1:26 ET); it is not a live box. The pack still refuses automatic destroy.

## Feature matrix

| Feature | Where | Rule |
| --- | --- | --- |
| Confirm Rent | `POST /api/rent` with `confirm: "RENT"` | No live Vast call. Dry-run does not install. |
| Coding computer | Role `coding`, **Install coding computer only** | Ollama + `granite4.2:8b-q8_0` + Aider + mission. No ComfyUI download. |
| Media computer | Role `video` or `image`, **Install media computer only** | ComfyUI on a different SSH host. Wan 2.2 5B only when chosen. No Granite install. |
| One computer later | Role `combined` | Not the default. VRAM mutex only. 24GB never loads Granite and Wan together. |
| Gallery | `/api/gallery` and `/api/gallery/media/<file>` | Lists ComfyUI `output/` plus the pack gallery. Thumbnails and video playback go through the :8787 tunnel. |
| Image box | Role `image` | Separate from video and from Granite. |
| Machine preset: Wan 2.2 video - RTX 4090 | Advanced → **This computer** → **Wan 2.2 video - RTX 4090**, then **I confirm RENT** + **Confirm Rent**. `GET /api/presets`. Files in `podcoder/presets/wan22_video_rtx4090/` | One verified US RTX 4090, ≤ $0.50/hr, ≥ 1000 Mbps down, 80 GB disk. ComfyUI + Wan 2.2 TI2V 5B, 704x1280, 121 frames @ 24 fps. Picking never rents; Confirm Rent only records the word. `controller.py --live` rents one box, budgets on the live Vast credit drop (default $1.50 cap, $0.10 margin), destroys after the last job. One Confirm Rent = one rent. Keys from `VAST_API_KEY` / `VAST_API_KEY_FILE` only. Separate from lip-sync. |
| Combined | Role `combined` only when chosen | Optional. Never auto-load Granite and Wan together on 24GB. |
| Bandwidth floor | Offer list + rent gate | `inet_down` ≥ 900 Mbps (the old Utah floor). Disk default 150GB. No live Vast call. |
| Former Utah | `58092881` | Historical 900 Mbps baseline only. Joseph shut it. Not a live never-destroy target. The pack still refuses automatic destroy of every instance. |
| Compute flip | `PODCODER_COMPUTE=local\|cloud` | ~8GB and ~16GB Aspire use `granite4.2:8b` Q4. ~32GB Aspire uses `profiles/local_ram32_q5.json` (`granite4.2:8b-q5_0`). Cloud uses `granite4.2:8b-q8_0`. |
| Download dry-run | `POST /api/download` with `"dry_run": true` | Runs the real install script and stops before any weight download. One click omits this flag and runs the full script. Status words follow that process: Waiting, Downloading, Ready. |
| Detect | **Detect** on the chat home, `POST /api/probe` | Reads GPU, VRAM, RAM, and disk. Picks what local Download installs. A laptop that is too small is told to Confirm Rent. Cloud Rent still auto-picks RTX 3090, 900 Mbps, 150GB. |
| Reverse translator | `granite_to_everyday.py` | Everyday English line first. Raw output is optional. No second model. Same line for local and cloud. |
| Wan prompt | `everyday_to_wan.py` | Everyday English → A1 prompt for Wan 2.2 5B. |
| Sign in | `POST /api/auth` | Email and password only. The password is stored as a scrypt hash. Confirm-email and password reset use `auth/dev-inbox.json` when `SMTP_HOST` is blank. No Gmail, OAuth, or SSO. |
| Sessions | `POST /api/sessions` | One signed-in person, many chats. A token lists only that person's history. Relay stays inside the same account. One Granite queue, cap 500. |
| Lifebook | `POST /api/memory` | 13 categories tag a line and keep a word for how that area is going. A note appears only when one category dominates the last 10 sessions or 10 days. No percentage. |
| Offline sync | `GET /api/sync` | Local JSON cache. Blank `SUPABASE_URL` stays offline. The SQL file is not applied. |
| Vault | `POST /api/vault` | Local encrypted store for email, username, password, EIN, SSN, named secrets, and OAuth tokens. Secrets are not logged. |

## Running independently

The laptop can keep working when the phone disconnects. These pieces stay on the machine. Blank env vars stay offline. Nothing here rents a computer.

| Piece | API | Offline behavior |
| --- | --- | --- |
| Jobs | `POST /api/jobs` | SQLite queue with status, logs, cancel, and retry. A Supabase note is queued locally and is not uploaded. |
| Agent | job kind `agent` | Plan, act, observe, retry. Shell is limited to `echo`, `printf`, `pwd`, `ls`, and `cat` inside the workspace. Local model name is `granite4.2:8b-q5_0`. Cloud name is `granite4.2:8b-q8_0`. |
| Cursor | `CURSOR_API_KEY` | If the key is set, the job selects the Cursor handoff and still returns an offline stub. |
| Scrape | job kind `scrape` | Fixture HTML via httpx and BeautifulSoup when those packages are installed. Browser actions are a local stub. Robots rules are on by default. |
| Routines | `POST /api/routines` | Cron expressions and a notify-me-when flag enqueue jobs. |
| Notifications | job done, needs approval | Web push and SMTP stay stubbed until `VAPID_*` or `SMTP_HOST` is set. |
| Vault connectors | `GET /api/connectors` | Gmail, GitHub, Dropbox, and a generic REST connector are config stubs. Client secrets are never returned. |
| Approvals | `POST /api/approvals` | Spend, send, and delete pause until the exact word `SPEND`, `SEND`, or `DELETE`. The action is not performed by the confirm step. |
| Memories | `POST /api/memories` | `podcoder_memories` mirror. Types are fact, preference, goal, and event. Categories are Lifebook words. Recall puts the current chat category first. |
| Backups | `POST /api/backup` | Aspire profile: incremental copy every 4 hours, plus immediately after a vault write or a finished job. Cloud profile: the same local copy plus a write-through note. `python3 podcoder/backups.py restore --state ... --id ... --dest ...` |
| Health | `GET /api/health` | Watchdog heartbeat. `scripts/aspire-always-on.sh` prints the Windows power settings. systemd user units live in `scripts/systemd/`. |
| 2FA | `POST /api/auth` op `enroll-totp` | Optional TOTP on the email and password account. Sign-in without enrollment is unchanged. |
| Charts | `POST /api/charts` | Template plus data. Lifebook sources use level or tag only. Hidden demo: `/widgets`. It is not linked from the chat page. |
| Transcripts | job kind `transcript` | Fixture captions or a sidecar next to a short audio file. `GET /api/quotes?q=&speaker=&category=` returns the quote, speaker, video, and timestamp link. |
| Emotion | `POST /api/emotion` | System prompt for the nine fruits of the Spirit, plus a qualitative fruit tag. No percentages. Turn it off with op `set` and `enabled: false`. |
| Humor | `POST /api/humor` | Sample bits are labeled sample. The agent does not pick a bit for vault, spend, or approvals. |

Live keys Joseph fills in `local/.env` when he wants them, all blank in git:

`SUPABASE_URL` (https://wxvjajecvklfjxppawdx.supabase.co), `SUPABASE_ANON_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT`, `PUSH_ENDPOINT`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `CURSOR_API_KEY`, `XAI_API_KEY`, `XAI_MODEL`, `XAI_BASE_URL`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, `DROPBOX_CLIENT_ID`, `DROPBOX_CLIENT_SECRET`, `REST_CONNECTOR_BASE_URL`, `HF_TOKEN`, `PODCODER_PROFILE`, `PODCODER_WORKSPACE`, `PODCODER_FETCH_ALLOW`.

Proven here without those keys: the queue, the sandboxed agent, fixture scrape, routines, notification stub, vault names, approval words, memory recall, backup restore, watchdog script text, TOTP, chart configs from 0 to 100, the hidden widget route, fixture transcripts, emotion tags, and sample humor. A real Supabase upload, a live Cursor run, a live browser, yt-dlp, faster-whisper, and pyannote still wait for Joseph's machine and keys.

## Requirements
- RTX 3090-class GPU pod, Python 3
- Official install path pulls `granite4.2:8b-q8_0` only when those weights are not already present
- Aider is installed on the box and used later only after ≥2 Granite raw FAILs (max 1 surgical pass). This change does not start calc coding gates.

## Granite-first policy
Default model `granite4.2:8b-q8_0`; never lead with Aider; `minRawFailsBeforeAider=2`. See `podcoder/GRANITE_FIRST_AIDER_POLICY.md`.

## Grok first, Granite when Grok is down

Chat, the everyday-English translator, session replies, the agent loop, coding missions, and Aider try Grok on the xAI API first. If the key is missing, or xAI returns 401, 429, or 5xx, or the call times out or the network fails, the same request falls back to IBM Granite 4.2 8B on local Ollama at `http://127.0.0.1:11434`. If both fail, the existing canned line is returned. The API field `backend` is `grok`, `granite`, or `canned`. `GET /api/probe` and `POST /api/probe` include the same order under `llm`.

Video and image stay on ComfyUI and Wan. Grok does not replace those.

The fast public model is `grok-4.3` (xAI documents it as the fast model, with low reasoning by default). Set `XAI_MODEL=grok-4.7` on the box if you want the flagship instead. Chat completions go to `POST https://api.x.ai/v1/chat/completions`.

xAI bills per token. The owner pays that bill. Granite on Ollama is the free offline fallback and does not add an xAI charge. Prices change; the Grok 4.3 rates published when this was wired were $1.25 per 1M input tokens and $2.50 per 1M output tokens under 200k prompt tokens, and double that at or above 200k. Confirm the current table at https://docs.x.ai/developers/models before you leave the key set.

On the Aspire or the cloud box, put the key in the environment of the process that runs `local/server.py` and `mission_server.py`. A blank key keeps every model call on Granite.

```bash
# local/.env on that machine, or the service environment. Never commit the real key.
XAI_API_KEY=your-key-here
XAI_MODEL=grok-4.3
XAI_BASE_URL=https://api.x.ai/v1
```

You can also put `XAI_API_KEY=` in `~/.config/simco-si/xai.env` or `/etc/simco/xai.env`, or point `XAI_SETTINGS_FILE` at a file outside this repo. The program will not read a key from a file inside the repo. The key is not logged, not returned by the API, and not written into git.

Aider, when the key is set, starts as `aider --model xai/$XAI_MODEL` against xAI's OpenAI-compatible API (`OPENAI_API_BASE` is set to `XAI_BASE_URL` for that process). When the key is unset, Aider stays on `ollama_chat/<granite tag>`.

Per-user model id, still not the key: `POST /api/settings` with `op: "set-model"` and `xai_model`. `XAI_MODEL` in the environment wins over that setting.

## Grok is the brain (Grok-only setup)

With a Grok key set, Grok is the only thing Simko SI needs. Granite, Ollama and GPU rental are optional and never gate chat or coding:

- Setup reports `chat_unlocked: true` and `brain: "grok"`, even on a computer too small for Granite. The Granite smoke-pass gate only applies when there is no key.
- Plain chat goes to Grok. If Grok can't be reached the reply says so; it never pretends.
- Coding jobs (still started by typing `RUN`) ask Grok for the files, then check them before saying Done: Python compile, `pytest` if there are tests, one run of the program (the one Grok names, or the single script it wrote), and a headless browser load of up to three `.html` pages. Any crash, failing test or page error is reported as "It didn't work…", with the file and line, never as Done.
- After a failure, typing "fix it" (or "fix that", "try again") starts a fix job straight away in the same project. Grok gets the original request, the error and the current files.
- xAI 429/5xx replies are retried twice (1.5 s, then 4 s) before the failure is shown.

Video is not made through Grok before 2026-11-03 (owner rule). Video stays on the cloud-pod ComfyUI/Wan path; `/api/probe` shows `llm.grok_video.allowed: false` with the date.

## Proven on this pack, without a Vast instance

Local Coding Download was run on the pack VM through `install-local-aspire.sh` itself. Ollama, curl, and Aider were stub programs so the huge weights were not pulled. The script still executed its own stages (`PODCODER_STAGE` ollama, pull, aider, smoke), printed `skip pull` for `granite4.2:8b-q5_0`, and ended with `PODCODER_LOCAL_SMOKE_PASS`. Install status moved Waiting, then Downloading, then Ready. That was not the dry-run sleep path. Pulling the real `granite4.2:8b-q5_0` weights still happens on Joseph's Aspire when he clicks Download there.

Local Video and Image Download call `install-video-comfy-wan.sh` and `install-image-role.sh`. A weak machine is told to Confirm Rent instead. Cloud scripts `install-on-pod-q8.sh`, the video script, and the image script were run offline after a recorded Confirm Rent. The SSH command named the script and the stub host. Nothing connected to Vast.

## When Joseph says Confirm Rent

```bash
bash podcoder/checklist-confirm-rent.sh
```

That command only prints the checklist. It does not create or destroy an instance.

## Boot
1. On Joseph's PC: `cd podcoder-translator-renter/local && bash start_local.sh` → http://127.0.0.1:8788/ is the two-bubble chat (`local/chat.html`). Pick Coding, Video, or Image. **Detect** reads this computer and says what Download will install. **Download** or **Rent** is the action. Confirm Rent still needs “I confirm RENT”. The older control panel stays at http://127.0.0.1:8788/translator.html.
2. **Confirm Rent** only after checking “I confirm RENT”. Dry-run does not install and does not enable chat/calc.
3. Pick the computer at Confirm Rent. **Coding computer** installs only Ollama + Granite + Aider. **Media computer** installs only ComfyUI, and Wan 2.2 5B only if that option is checked. Use a different SSH host for each. Do not stack the downloads on one rent.
4. After Confirm Rent, the install matches that computer. Coding smoke (`ollama list`, generate, `aider --version`) unlocks chat/calc. The media gallery lists `ComfyUI/output` through the :8787 tunnel for that media computer.
   - SSH host/port on the rent POST (or `PODCODER_SSH_*` in `local/.env`) starts the role script automatically.
   - Coding runs `install-on-pod-q8.sh`. Video runs `install-video-comfy-wan.sh`.
   - Without SSH, the rent response is `install: "needs_ssh"`. Use **Install stack** (`POST /api/install`). It is refused until Confirm Rent succeeded.
5. On a coding box, `install-on-pod-q8.sh` uses official `curl https://ollama.com/install.sh | sh` if `ollama` is missing; starts `ollama serve` if `:11434` is down; pulls `granite4.2:8b-q8_0` only when `ollama show` does not already see the weights; `pip install aider-chat`; smoke (`ollama list`, a generate call, `aider --version`). Smoke failure fails Install. Only then does it copy `podcoder/` to `/opt/podcoder` and start mission_server on `:8787`.
6. Tunnel: `ssh -p <PORT> -L 8787:127.0.0.1:8787 root@<POD_IP>`. Translator chat/calc stays disabled until that smoke pass. Then use the UI or:

```bash
curl -s -X POST http://127.0.0.1:8787/api/mission -H 'Content-Type: application/json' \
  -d @podcoder/sample-mission-dryverify.json
curl -s http://127.0.0.1:8787/api/mission/status/<mission_id>
curl -s http://127.0.0.1:8787/api/install/status
```

Re-running the install script is safe: it will not start a second copy while the lock is held, and it skips the model pull when the weights are already present. It never calls Vast destroy.

## Tree
```
README.md
local/      translator.html server.py start_local.sh .env.example README.md
podcoder/   install-on-pod-q8.sh install-on-pod.sh install_hook.py
            pod_autocode_runner.py mission_server.py podcoder_http.py start_mission_server.sh
            everyday_to_granite.py translator-everyday-typea-master-batch.json
            master-batch-template.json GRANITE_FIRST_AIDER_POLICY.md
            ONPOD_MASTER_LOOP.md sample-mission-dryverify.json seeds/translator.html
```
