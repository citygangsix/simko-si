# Simco SI store packaging

## Listing kit files

| File | What it is |
| --- | --- |
| `listing.md` | Paste-ready names, descriptions, keywords, and App Review notes |
| `privacy-policy.md` / `privacy-policy.html` | Privacy policy. Host the HTML on a site Joseph controls. |
| `age-rating.md` | Apple age rating and Google IARC answers |
| `export-compliance.md` | Encryption and export answers (`ITSAppUsesNonExemptEncryption` = false) |
| `play-data-safety.md` | Play data safety form and Apple privacy labels |
| `screenshots/` | Phone, Z Fold cover and inner, and iPad screenshots, captured headless (`tools/capture_screenshots.py`) |
| `graphics/` | Play 512×512 icon and 1024×500 feature graphic. The Apple 1024 icon is `simco-mobile/brand/icon-1024.png`. |
| `BUILD-RELEASE.md` | Signed Android build and the iOS TestFlight workflow |
| `OWNER-CHECKLIST.md` | Steps only Joseph can do (fees, keys, secrets, submission) |

This is a listing draft and a submission checklist. It does not submit the app, create a developer account, or store a signing key.

Change the application id in `simco-mobile/app.config.json`, then run `node simco-mobile/set-app-id.mjs <new.id>` and `npx cap sync` from `simco-mobile/`. The suggested id is `com.simkosi.simcosi`. The name on both stores is **Simco SI**.

The phone app is a client. Chat, the sea turtle setup screen, and the rest of the web UI are bundled in the app. Hardware detection, Granite, Ollama, Aider, the translator, and setup run on the computer whose address the person types on the turtle screen. The app does not ship with a tunnel URL.

## Listing draft

| Field | Text |
| --- | --- |
| Name | Simco SI |
| Short description (80 characters or fewer) | Chat with your own computer. It picks and runs the local model. |
| Category | Productivity. Developer Tools is a reasonable alternate if the store asks for a tools category. |
| Keywords | simco, local model, granite, ollama, private chat, offline assistant, self hosted |

Short description length: "Chat with your own computer. It picks and runs the local model." is 62 characters.

### Full description

Simco SI is a private chat window for a computer you already run.

You type everyday language. That computer turns it into the right prompt for the Granite model it chose for its own memory and graphics chip, then turns the model's reply back into everyday language. The phone does not download the model. The computer does.

On first launch, a sea turtle screen asks for that computer's address. Simco SI then shows the computer detecting itself, choosing Ollama, Granite, and Aider, and unlocking chat. Tools, Lifebook notes, and Advanced stay on the same computer.

Your chats stay on the machine you point at. Simco SI does not include a public account, a public model host, or a rented graphics card.

### Privacy policy

Both stores require a privacy-policy URL before review.

The policy should say, in plain language:

- The app stores the computer address on the device.
- Account email and password, if the person signs in, are sent only to that computer.
- Chat text is sent only to that computer.
- The app does not use advertising, tracking SDKs, or a Simco-operated account server.
- Lifebook notes and the encrypted vault stay on the computer the person configured.
- Clearing the app's storage, or deleting the app, removes the saved computer address.
- If they later add crash reporting or analytics, the policy has to name it before the app does.

Host the policy on a site Joseph controls. Do not point the listing at a temporary tunnel.

### Data safety (Google Play)

Answer from what this build actually does:

| Question | Answer |
| --- | --- |
| Does the app collect or share user data? | Yes, data is sent off the phone, but only to the computer address the person entered. |
| Is that data shared with third parties? | No, not by the app. The computer is the person's own machine. |
| Data types | Email address (optional account), app interactions (chat messages), device or other IDs are not collected by the app. |
| Is collection optional? | The computer address is required for chat. Sign-in is optional. |
| Encrypted in transit | Only when the address is https. An http address on a home network is not encrypted. Say that plainly. |
| Can users request deletion? | Deleting the app removes the saved address. Chats stored on the computer are deleted there, not from a Simco server. |
| Ads | No. |
| Tracking | No. |
| Data sold | No. |

### Screenshot list

Capture these on a phone or emulator and upload the store's required sizes. The pictures in `/opt/cursor/artifacts/` are reference shots from this packaging pass.

1. Launch / sea turtle setup, asking for the computer address.
2. Setup progress: Granite, Ollama, and Aider chosen for that computer.
3. Messenger, with the chat list and a thread.
4. Tools sheet, including Lifebook and Computer.
5. Sign-in fields.
6. Fold-style narrow layout, if you want a second phone size.

Apple also wants a 1024×1024 icon with no transparency and no rounded mask. Google wants a 512×512 icon. Both are generated from `simco-mobile/brand/`.

## Submission checklist

Do these yourself. This repository cannot do them.

1. Apple Developer Program, 99 USD per year, at developer.apple.com. Enrollment is in Joseph's name or the company name that should appear on the store.
2. Google Play Console, a one-time 25 USD registration fee, at play.google.com/console.
3. Create a signing key on a machine you control. For Android, a Play App Signing upload key. For Apple, a distribution certificate and a provisioning profile created in Xcode or the developer portal. Keep the keystore and the p12 outside this repo. Do not commit `.jks`, `.keystore`, `.p12`, `.mobileprovision`, or passwords.
4. Put the privacy-policy URL into both listings.
5. Complete the Google Data safety form with the answers above, and Apple's privacy nutrition labels: contact info (optional email) and user content (chat), not used for tracking, not linked to a Simco identity.
6. App Store review risk: an app that is mainly a packaged web view can be rejected under guideline 4.2 if it feels like a website wrapper with little native value. This build's native piece is the on-device host address and the bundled UI. Be ready to explain that chat, model choice, and setup depend on the person's own computer, and offer a TestFlight build that demonstrates that flow. If review asks for more native function, that is a product change, not a resubmit of this same binary with a new description.
7. Android internal testing: upload the AAB to an internal testing track, add tester emails, install from the Play opt-in link. The debug APK in the artifacts folder is for a sideload or an emulator, not for the Play listing. Play requires a signed AAB.
8. iOS testing: open `simco-mobile/ios/App/App.xcworkspace` on a Mac, set the signing team, archive, and upload to TestFlight. This Linux build cannot compile the iOS app. A Mac, macOS CI, or a Cursor macOS pool is required for that archive.
9. Before upload, run the app against the Aspire or the cloud computer, not against a temporary public tunnel. Confirm the turtle screen shows that computer's detection and that Send returns a reply.
10. Age rating: no unrestricted web browsing, no ads, no user-generated public feed. Answer the questionnaires for chat with an assistant. If chat can produce unrestricted text, expect a 12+ or teen-style rating rather than 4+.

## What is already built

- One Capacitor project, `simco-mobile/`, for both stores.
- Bundled `chat.html`, the sea turtle screen, Advanced, and the reef images.
- Android release AAB and APK, signed with the upload key when `SIMCO_KEYSTORE_PROPERTIES` points to a keystore outside the repo (see `BUILD-RELEASE.md`).
- An iOS Xcode project. Building it needs macOS. `.github/workflows/ios-testflight.yml` archives and uploads it to TestFlight from a GitHub macOS runner when started by hand.

## What Joseph provides before a real submission

- The Apple Developer membership and the Google Play Console account, including the fees above.
- A privacy-policy URL on a site he controls.
- Android upload keystore and Apple distribution signing, stored outside the repo.
- A Mac to archive the iOS app, or a macOS CI runner.
- The address of the Aspire or other computer that should appear in the screenshots, with Simco SI already running there.
- A decision on the final application id if `com.simkosi.simcosi` should change.
