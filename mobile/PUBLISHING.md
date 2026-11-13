# Publishing Simko SI

This file is the checklist. It does not publish anything, and it does not create an Apple or Google account.

The wrapper is a website shell. `mobile/capacitor.config.json` points `server.url` at `https://simkosi.com`. New screens stay off until the matching `platform` flag in `simkosi-private/config.php` is true. Do not turn those flags on just to ship the store listing.

## Fees Joseph would pay himself

These are the public account fees, not a quote from this repo:

- Apple Developer Program: US$99 per membership year. Required before an iOS build can be uploaded. Enrolling is Joseph's decision.
- Google Play Console: US$25 once, for the developer account.
- Apple and Google commissions apply to digital goods sold inside the app (often 15% or 30%). Simko SI's $9.99/month plan is a Stripe checkout on the website. Keep that payment on the website. Do not add an in-app purchase until Joseph decides to.

No store fee is charged by uploading nothing. This repo does not upload.

## iOS

1. Enroll at https://developer.apple.com/programs/ if the account does not exist yet.
2. Register the App ID `com.simkosi.simcosi`.
3. If Google or another social button ships, Apple requires Sign in with Apple as well. Those buttons stay hidden while the client ids are empty.
4. In App Store Connect, create the app record for Simko SI. Do not submit a build from this environment.
5. On a Mac with Xcode, add the iOS platform to the Capacitor project, set the bundle id to `com.simkosi.simcosi`, archive, and upload with the account above.
6. Fill the privacy nutrition labels. The site can store an account, chats, and, only when flags are on, memories, vault items, and child profiles.
7. Submit for review only after Joseph signs off on the mockups and the flags he wants in that build.

## Android

1. Pay the US$25 Play Console registration if it is not already paid.
2. Create the app in Play Console. Package name `com.simkosi.simcosi`.
3. Build an Android App Bundle from the Capacitor Android project on a machine Joseph controls. Do not upload it from here.
4. Complete the data-safety form to match the flags that are actually on.
5. Roll out to production only after Joseph says so.

## What stays undone on purpose

- No Apple enrollment
- No Play Console signup
- No screenshots uploaded to either store
- No signing keys generated for a store upload
