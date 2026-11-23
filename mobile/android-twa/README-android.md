# Simko SI for Android: Trusted Web Activity (Bubblewrap 1.27 project in `project/`)

Package `com.simkosi.app` · versionName 1.0.0 · versionCode 1 · minSdk 24 · targetSdk 36 · permissions: none beyond the TWA receiver (no INTERNET, no AD_ID: Chrome does the networking).

## Why TWA and not Capacitor on Android
- Google's own recommended way to ship a PWA on Play; the app runs in the user's real Chrome, so Google sign-in, passkeys/password autofill, web push and updates work the same as the website, and every deploy of simkosi.com updates the app with no new upload.
- Play policy is fine with it as long as the site behaves like an app (full screen once Digital Asset Links verify, no browser UI, offline handling). Verified on the emulator: full screen with the upload key.
- Apple has no TWA equivalent, so iOS uses the Capacitor shell in `../ios-capacitor`.

## Build (box, free)
`/workspace/simkosi-store-apps/build-android.sh` → `/workspace/simkosi-store-apps/out/`:
- `simkosi-1.0.0-vc1-debug.apk` (debug key: shows a Chrome URL bar because the debug key isn't in assetlinks.json; for quick installs)
- `simkosi-1.0.0-vc1-release-unsigned.aab` + `-release-unsigned.apk` (sign with the upload key in `/workspace/simkosi-store/secrets`, or upload the signed one at `/workspace/simkosi-store/android/release/`)

## After the first Play upload
Add the Play App Signing SHA-256 to `../well-known/assetlinks.json` and deploy it, or the store-installed app shows a URL bar.

## Icons / splash
Adaptive icon (mipmap-anydpi-v26, maskable art inset 8.5dp), legacy mipmaps mdpi to xxxhdpi, splash drawables for all densities, Play icon 512 and feature graphic 1024x500 in `/workspace/simkosi-store/assets/graphics`.
