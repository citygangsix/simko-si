# Owner-only checklist (Joseph)

Nothing here has been done. Nothing has been submitted or paid for.

## Accounts and money

- [ ] **Apple Developer Program**: 99 USD per year, developer.apple.com/programs/enroll. Decide whether to enroll as an individual (seller shown as "Joseph Simko") or as an organization (needs a D-U-N-S number).
- [ ] **Google Play Console**: one-time 25 USD, play.google.com/console. New personal accounts must run a **closed test with at least 12 testers for 14 days** before production access.

## Signing and secrets

- [ ] **Back up the Android upload key offline.** Copy `simco-si-upload.jks` and `keystore.properties` from `/workspace/simco-si-keys/` on the build box to a password manager or an encrypted drive. Save the passwords in the vault, not in chat or git.
- [ ] **Play App Signing**: accept it when creating the app in Play Console, then upload the signed AAB.
- [ ] **App Store Connect API key**: Users and Access → Integrations → App Store Connect API → generate a key with the App Manager role. Download the `.p8` (it can be downloaded only once).
- [ ] **GitHub secrets** in citygangsix/og-raw-frontier-ai: `ASC_KEY_ID`, `ASC_ISSUER_ID`, `ASC_KEY_P8`, and `APPLE_TEAM_ID`.
- [ ] **Create the App Store Connect app record**: My Apps → + → New App, bundle id `com.simkosi.simcosi`, name Simco SI, primary language English (US). Register the bundle id under Identifiers first if it isn't offered.

## Listing content

- [ ] Host `store/privacy-policy.html` on a site you control, fill in the contact email, and paste the URL into both stores.
- [ ] Support URL, plus a "delete my data" URL for Play (a short page that says deleting the app removes local data and that host data is deleted on the host computer is enough).
- [ ] Re-capture `02-setup-detected` on the Aspire or the target computer, so the shot shows real hardware.
- [ ] Give App Review a reachable https Simco SI host address, or a demo video. Without a host, the reviewer sees only the turtle screen.
- [ ] Play's AI-generated content policy expects an in-app way to report offensive output. Decide whether to add a "Report reply" action before production. That's a UI change, so do a mockup first.

## Submission (only when you say go)

- [ ] Play: create the app, then complete App content (privacy policy, ads, app access, content rating from `age-rating.md`, target audience, data safety from `play-data-safety.md`). Upload `simco-si-1.0-release.aab` to Internal testing first, then Closed testing.
- [ ] Apple: start the "iOS TestFlight" workflow, test the build in TestFlight, then complete App Privacy, Age Rating, the listing from `listing.md`, and the screenshots. Submit for review.
