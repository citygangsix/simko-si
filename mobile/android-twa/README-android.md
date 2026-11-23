# Simko SI for Android (Trusted Web Activity, generated with Bubblewrap core 1.27)

Package: `com.simkosi.app` · versionName 1.0.0 · versionCode 1 · minSdk 24 · targetSdk 36 (meets Play's current target-API rule)

## Files
- `release/simkosi-1.0.0-vc1-release.aab` — **upload this to Play Console** (signed with the upload key below).
- `release/simkosi-1.0.0-vc1-release.apk` — same build as an APK for side-loading on a test phone (`adb install`).
- `twa/` — the Gradle project (open in Android Studio or rebuild with `../build-aab.sh`). `twa/twa-manifest.json` is the Bubblewrap config.
- Upload keystore + passwords: `/workspace/simkosi-store/secrets/` (0600, never printed). **Back these up off the box today** (password manager / private Dropbox / USB). Without them, the app can't be updated until Google resets the upload key.

## Upload key fingerprint (public, already in https://simkosi.com/.well-known/assetlinks.json)
SHA-256 `73:C5:43:AE:60:C1:E8:50:86:EF:69:69:86:FA:EF:6A:9A:E3:4F:84:7D:9C:7A:D8:A9:13:08:CA:A0:E1:4E:39`
Google's Digital Asset Links API already returns this statement for simkosi.com → com.simkosi.app.

## One thing to do after the first upload
Play Console re-signs the app with **Play App Signing**. Copy the *App signing key* SHA-256 from Play Console → Test and release → Setup → App signing, and add it as a second fingerprint in `/.well-known/assetlinks.json`. Until then, the Play-installed app would show a browser address bar instead of full screen.

## Rebuild
Bump `appVersionCode` / `appVersionName` in `twa/twa-manifest.json` and `versionCode`/`versionName` in `twa/app/build.gradle`, then run `./build-aab.sh` (uses the JDK 17 + Android SDK under `/workspace/simkosi-store/toolchain`).
