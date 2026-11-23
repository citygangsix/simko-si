# Play Data safety + Apple App Privacy answers (DRAFT; matches privacy.html effective Nov 23 2026 and the live build flagship5)

## Google Play Data safety
- Does the app collect or share required user data types? **Yes, collects.** Shared with third parties: **No** (xAI, Hostinger and Stripe are service providers processing on our behalf, which Play does not count as sharing).
- Is all data encrypted in transit? **Yes** (HTTPS only).
- Do you provide a way for users to request deletion? **Yes**: in app (account menu > Delete account) and https://simkosi.com/support#delete-account.
- Independent security review: No. Families policy: not targeted at children.

| Play data type | Collected | Ephemeral? | Required/optional | Purposes |
|---|---|---|---|---|
| Personal info > Email address | Yes | No | Required | Account management |
| Personal info > User IDs (Google/Apple sign-in ID, account number) | Yes | No | Required | Account management |
| Personal info > Name (child profile display name, set by parent) | Yes | No | Optional | App functionality |
| Financial info > Purchase history (subscription status, Stripe customer ID) | Yes, only if paid plan is on | No | Optional | App functionality |
| Messages > Other in-app messages (chats, memories, routines, Lifebook notes, reports) | Yes | No | Required | App functionality |
| Photos and videos > Photos (pictures you upload or create) | Yes | No | Optional | App functionality |
| Audio > Voice or sound recordings (mic clips) | Yes | **Yes** (transcribed, not kept) | Optional | App functionality |
| Files and docs (PDF/Word/Excel/text attachments) | Yes | No | Optional | App functionality |
| App activity > App interactions (message/picture counts) | Yes | No | Required | App functionality, Fraud prevention/security |
| App info and performance > Crash logs, Diagnostics (server error log, cookieless browser error reports) | Yes | No | Required | App functionality, Analytics |
| Device or other IDs | No | | | |
| Location, Contacts, Calendar, Health, Web history | No | | | |
No ads, no advertising ID (the TWA does not request AD_ID; declare "No" for advertising ID in Play Console).

## Apple App Privacy
Data **linked to the user**, used for **App Functionality** only:
- Contact Info: Email Address; Name (child profile display name)
- User Content: Other User Content (chats, memories, routines, notes), Photos or Videos, Audio Data, Customer Support (reports)
- Identifiers: User ID
- Purchases: Purchase History (only if the paid plan is on in the app)
- Usage Data: Product Interaction
- Diagnostics: Crash Data, Other Diagnostic Data (also "Analytics" purpose for the cookieless telemetry)
**Tracking: No.** No third-party ads or SDKs that track.

## Privacy policy gap to fix before submission
privacy.html does not yet mention **uploaded files and photos** (attachments sent to chat). Add one line under "Your content" (wording change = Joseph's OK).
