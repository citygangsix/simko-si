# Simko SI store readiness (Nov 23 2026, live build flagship5-20261123)
Branch `cursor/simkosi-store-apps` (from 3593066). Nothing submitted, no developer accounts, no fees, the website was not redeployed, nobody contacted.

## What is where
| Item | Path |
|---|---|
| Android TWA Gradle project | `mobile/android-twa/project/` (README-android.md explains TWA vs Capacitor) |
| iOS Capacitor 8 Xcode project | `mobile/ios-capacitor/` (`ios/App/App.xcodeproj`, SPM, no CocoaPods) |
| Free iOS CI (unsigned build + simulator run) | `.github/workflows/simkosi-ios-unsigned.yml` |
| `.well-known` drafts (not uploaded) | `mobile/well-known/` (assetlinks.json with Play-signing placeholder, apple-app-site-association with Team ID placeholder, .htaccess snippet) |
| iOS entitlements draft | `mobile/ios-capacitor/entitlements-draft/App.entitlements` |
| Listings, data safety, App Privacy, content rating, reviewer account | `mobile/store-metadata/` |
| Blockers | `mobile/STORE-POLICY-GAPS.md` |
| Test evidence | `mobile/test-results/` |
| Box-only artifacts | `/workspace/simkosi-store-apps/out/` (APK/AAB), `/workspace/simkosi-store-apps/ios-ci/` (simulator .app, unsigned .xcarchive), `/workspace/simkosi-store-apps/screenshots/` (store-size shots), `/workspace/simkosi-store/secrets/` (upload key, 0600) |

## App identity
Name Simko SI · id `com.simkosi.app` (free on both stores) · 1.0.0 / code 1 (iOS 1.0 build 1) · Android minSdk 24, targetSdk 36 · iOS 15+.
Privacy https://simkosi.com/privacy · Terms https://simkosi.com/terms · Support https://simkosi.com/support · Account deletion https://simkosi.com/support#delete-account (all live, 200).

## Cost to publish (prices checked Nov 23 2026)
| Item | Cost | Needed for |
|---|---|---|
| Google Play developer account | $25 once | Play |
| Apple Developer Program | $99 / year | App Store, TestFlight, real-device installs |
| D-U-N-S number | $0 (free from Dun & Bradstreet, about 1 to 4 weeks) | Organization accounts on both stores |
| iOS builds | $0: GitHub Actions macOS on this public repo (used today), Xcode Cloud 25 h/month included with the Apple membership, Codemagic 500 free M2 min/month, or Joseph's Mac | Signed .ipa upload |
| Cloud Mac if needed | MacinCloud pay-as-you-go $1/h or $4/day; managed from $25/month | Only if no Mac and CI signing isn't wanted |
