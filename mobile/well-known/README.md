# Files for https://simkosi.com/.well-known/ (DRAFTS, not uploaded)

| File | Live today | What to do |
|---|---|---|
| `assetlinks.json` | Yes, with the upload-key fingerprint only | After the first Play upload, replace `PLAY_APP_SIGNING_KEY_SHA256_FROM_PLAY_CONSOLE` with the App signing key SHA-256 from Play Console (Test and release > Setup > App signing) and deploy. Without it the Play-installed app shows a Chrome address bar. `get_login_creds` lets Android offer saved simkosi.com passwords in the app. |
| `apple-app-site-association` | No (404) | Replace `APPLE_TEAM_ID` with the 10-character Team ID once the Apple Developer account exists, deploy to `public_html/.well-known/apple-app-site-association` (no extension) plus `htaccess-snippet.conf`. Then turn on Associated Domains + Push Notifications in Xcode (or copy `../ios-capacitor/entitlements-draft/App.entitlements`). Gives universal links and iOS password AutoFill for simkosi.com. |

Check after deploy:
- `curl -sI https://simkosi.com/.well-known/apple-app-site-association` → 200, `content-type: application/json`, no redirect.
- `https://digitalassetlinks.googleapis.com/v1/statements:list?source.web.site=https://simkosi.com&relation=delegate_permission/common.handle_all_urls`
