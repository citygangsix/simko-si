# Simko SI on the web

The page keeps the uploaded messenger: left chat list, right conversation, foldable cover and inner screen, tools drawer, lifebook, themes, and voice. Grok is called only from PHP. The key lives in `simkosi-private`. There is no per-person or daily message cap.

| feature | status | reason |
| --- | --- | --- |
| New Chat, about 10 recent chats, switch chats | works | SQLite in `simkosi-private/data`. The list is the 10 most recently updated chats. Older chats stay stored. |
| Send to other chat (relay) | works | `api/sessions.php` writes a "sent to" line on the source chat and a "from" line on the destination. Both must belong to the signed-in user. |
| Search chats | works | Signed out, the 10 sample chats filter on this page. Signed in, search hits that account's titles and messages. |
| Email and password sign up, sign in, sign out | works | `password_hash` / `password_verify`. An HttpOnly `simko` cookie plus the token the existing page already stores in `sessionStorage`. |
| Email confirm | partial | No mail server is wired up. In `mail_mode=dev` (the default) the confirm token is shown in the tools drawer, same idea as the original dev inbox. Set `mail_mode` to `smtp` only after a mailer exists; this build does not send mail. |
| Password reset | partial | Same dev-token path. The token expires after one hour. Real delivery needs a mailer this host does not run. |
| Chats scoped to the account, with a browser cache | works | Server rows are the source of truth. The browser also keeps `localStorage` key `simko.cache.v1` so a failed reload can still show the last list. |
| Supabase project `wxvjajecvklfjxppawdx` | partial | Config hook only. `enabled` defaults to false. The code refuses any other project ref, and chat does not wait on Supabase. |
| Grok replies | works | `POST /api/simco/turn` reads the key from private config and calls `https://api.x.ai/v1/chat/completions`. Default model is `grok-4.7` and is configurable. Recent messages from that chat are sent with the new line. |
| No usage caps | works | No per-IP limit and no daily cap. Requests still have to be POST JSON from this site, and a single message over 8000 characters is refused as malformed. |
| Microphone | works | The uploaded client records with `MediaRecorder` and posts to `/api/voice/transcribe`, which proxies xAI `/v1/stt` (`grok-voice-transcribe-2.0`). If the browser cannot record, it uses the Web Speech API and types the words into the same box. |
| Spoken replies and previews | works | `GET /api/voice/speak` proxies xAI `POST /v1/tts` and returns audio. If that audio fails, the page speaks with `speechSynthesis`. Speed 0.7–1.5 is forwarded. |
| 28 sea-creature voices | works | The uploaded `simco-voice.js` loads names from `/api/voice/voices` (they are not listed in that file). This site serves Coral, Kelp, Manta, Nautilus, Dolphin, Orca, Turtle, Seahorse, Starfish, Anemone, Urchin, Octopus, Squid, Jellyfish, Manatee, Walrus, Seal, Otter, Marlin, Ray, Crab, Lobster, Shrimp, Clownfish, Angelfish, Puffer, Eel, and Whale. Each maps to one built-in xAI TTS voice. |
| Foldable layout | works | The original CSS is unchanged: one pane on a cover (narrow or short), two panes on a near-square inner screen, and hinge rules for viewport segments. |
| Connected dot, auto-connect | works | On load the page calls `/api/health`. The dot means this browser reached Simko SI. It does not ask you to pick a machine. |
| Cloud / Rent / Local labels | works | Those three controls are not shown. The website always talks to Grok. |
| Detect my computer | works | In the browser: OS from the user agent, `hardwareConcurrency`, `deviceMemory` when the browser exposes it, WebGL renderer, and a WebGPU adapter when present. The reply names a recommended stack. Nothing is installed. |
| Download | partial | No installer files are in this repo. The button says "Desktop app download coming soon" until `installers` in private config lists https links. |
| Advanced | partial | The control is in the tools drawer. It explains that the translator stays in the desktop app. There is no `/translator.html` on this host. |
| Confirm Rent | partial | The sheet explains that renting would reserve a GPU computer for a local model. Confirm Rent does not run here and does not call a rental provider. It tells you the desktop app is where that happens. |
| Video and image gallery | works | Choosing Video or Image shows a static gallery. The first item is the sea-turtle loop. The second is the poster still. The upload had the role buttons and no gallery markup; this is the web view for those roles. |
| Turtle background | works | Fixed, muted, autoplaying, looping, `playsinline` mp4. The poster is the fallback and the page background. A dark gradient keeps the type readable. The file is not reversed or re-encoded. |
| Lifebook | works | Nine life areas. The buttons use qualitative words (not discussed, in play, strained, doing well). Counts are only inside the Counts disclosure. |
| Themes | works | Reef and Plain, stored in `localStorage` (`simcoTheme`). No theme server. |
| Sample chats before sign-in | works | The original ten demos stay on the signed-out list. Sending, new chats, and relay ask you to sign in. |
| Raw transcript disclosure | partial | The Raw disclosure is still in the layout. Web replies are everyday text, so it stays closed. |
| Point the page at another computer | not on web | `simco-client.js` still ships, and on the native app it can rewrite `/api` to a computer you name. On this website `data-simko-web="1"` keeps every call here. |
| Local Granite, Ollama, Aider, calculator HTML jobs | not on web | Shared hosting cannot install or run those tools. Coding and calculator lines are answered by Grok in everyday words. `RUN` does not start a job on a GPU box. |
| Turtle screen that configures this computer | partial | The screen still opens from Sea turtle. Re-detect runs the browser probe. Setup check and Download say the desktop app is what installs a local model. |
| Real outbound email | not on web | This app has no SMTP transport. Confirm and reset use the on-screen token. |
| One-shot JSON reply (not a live token stream) | works | The uploaded client waits for one `everyday` string. `chat.php` returns that. It does not stream tokens. |
