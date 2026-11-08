# Export compliance

## Answer

`ITSAppUsesNonExemptEncryption` is set to `false` in `simco-mobile/ios/App/App/Info.plist`. With that key, App Store Connect does not ask the encryption question on each upload.

If App Store Connect asks anyway:

| Question | Answer |
| --- | --- |
| Does your app use encryption? | Yes. It uses HTTPS. |
| Does your app qualify for any of the exemptions in Category 5, Part 2 of the EAR? | Yes. It uses only encryption built into the operating system, through HTTPS (TLS) in the system web view, for its network requests. |
| Does your app implement any encryption algorithms that are proprietary or not accepted as standard? | No |
| Does your app implement standard encryption algorithms instead of, or in addition to, using or accessing the encryption in Apple's operating system? | No |
| Is your app going to be available on the French App Store? | Yes. No French declaration is needed for OS-provided TLS only. |

No CCATS or year-end self-classification report is required for an app that only calls the OS's HTTPS stack.

## Facts behind the answer

- Native dependencies: `@capacitor/core`, `@capacitor/ios`, and `@capacitor/android` 7.4.3 only. There are no crypto libraries, no VPN, and no end-to-end messaging protocol.
- The bundled web UI makes `fetch` requests to the address the user enters. TLS is handled by WKWebView on iOS and by the Android System WebView.
- The "encrypted vault" mentioned in the app lives on the user's computer (the Simco SI host), not in the phone app.

## Google Play

Play has no separate export form. In Play Console, under Pricing and distribution, leave US export laws acknowledged. Nothing else is needed for HTTPS-only apps.

## When to revisit

Change this answer before release if the app ever adds its own encryption, such as an on-device encrypted store, end-to-end encrypted chat, or a bundled crypto library like libsodium or OpenSSL.
