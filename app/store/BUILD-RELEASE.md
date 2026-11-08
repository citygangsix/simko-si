# Building the store binaries

## Android: signed AAB and APK

The release build signs itself only when a keystore properties file exists **outside the repo**. Without that file, `bundleRelease` and `assembleRelease` still work, but the output is unsigned.

`keystore.properties` (keep it next to the `.jks`, never in git):

```
storeFile=/absolute/path/to/simco-si-upload.jks
storePassword=...
keyAlias=simco-si-upload
keyPassword=...
```

Build:

```
cd simco-mobile
./sync-www.sh && npx cap sync android
cd android
export SIMCO_KEYSTORE_PROPERTIES=/absolute/path/to/keystore.properties   # default: ~/simco-si-keys/keystore.properties
export SIMCO_VERSION_CODE=1 SIMCO_VERSION_NAME=1.0                       # bump the code on every Play upload
./gradlew bundleRelease assembleRelease
```

Outputs:

- `app/build/outputs/bundle/release/app-release.aab`: upload this to Play.
- `app/build/outputs/apk/release/app-release.apk`: for sideloading or testers.

Requirements: JDK 21 and the Android SDK (platform 35, build-tools 35). `*.jks`, `*.keystore`, and `keystore.properties` are git-ignored in `simco-mobile/android/`.

Upload key in this packaging pass: alias `simco-si-upload`, RSA 4096, valid until 2054.

- SHA-256 `18:EA:83:50:D1:31:2C:42:56:D0:BD:52:5A:5E:DF:53:CF:6B:43:0D:3B:9F:53:15:F5:22:8B:69:D3:32:89:71`
- SHA-1 `2F:A6:06:42:66:C6:33:C5:F7:50:DB:F5:46:3D:DD:97:33:BE:57:EF`

Enroll in **Play App Signing**: Google holds the app signing key, and this key is only the upload key. If the upload key is lost, Play support can reset it.

## iOS: TestFlight from GitHub Actions

`.github/workflows/ios-testflight.yml` runs only when started by hand (Actions → "iOS TestFlight" → Run workflow). It runs on `macos-latest`, archives `simco-mobile/ios/App/App.xcworkspace` with automatic signing through an App Store Connect API key, and uploads the build to TestFlight.

Repository secrets it needs:

| Secret | Value |
| --- | --- |
| `ASC_KEY_ID` | Key ID of an App Store Connect API key with the App Manager role (or Admin) |
| `ASC_ISSUER_ID` | Issuer ID shown on the same Keys page |
| `ASC_KEY_P8` | Contents of the downloaded `AuthKey_XXXX.p8`, either raw PEM or base64 |
| `APPLE_TEAM_ID` | 10-character Team ID from developer.apple.com → Membership |

The App Store Connect app record for bundle id `com.simkosi.simcosi` must exist before the first upload. The build number is the workflow run number. The marketing version is an input that defaults to 1.0.
