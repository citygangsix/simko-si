# Store policy check — Simko SI (Nov 23, 2026)
| Rule | Status | What's needed |
|---|---|---|
| Apple 5.1.1(v) / Play account deletion | Built on branch (commit e583f32), **not live** | Joseph OKs mockup → deploy. Web deletion route = support.html#delete-account |
| Privacy policy URL (both stores) | Draft page on branch, **not live** | Joseph approves wording + support email |
| Terms URL / Support URL (Apple) | Draft pages on branch, **not live** | Same |
| Play AI-generated content policy (in-app reporting) | "Report this reply" flag built on branch, **not live** | Mockup OK → deploy. Reports land in simkosi-private/data/ai-reports.jsonl; someone must review them |
| Apple 4.8 Sign in with Apple | Google sign-in is ON live; iOS app hides it (live helper), leaving email+password, so 4.8 doesn't apply | Optional later: configure Apple sign-in (needs Apple account: Services ID + key) |
| Google OAuth in embedded webview | Blocked by Google in WKWebView → hidden in iOS app; works in Android TWA (real Chrome) | none |
| Apple 3.1.1 / Play Payments (Stripe $9.99/mo + paid pictures) | Paywall flag is OFF live today. If turned on: US storefront may link to web checkout (Apple 3.1.1(a) since May 1 2025; Play US external-links / alternative-billing programs need enrollment and fees from Oct 1 2026). Outside the US both stores require their own billing | **Decision:** release US-only with web checkout, or add Apple IAP / Play Billing, or hide buying in the apps |
| Apple 4.2 minimum functionality | iOS shell has native offline screen, splash/icons, haptics, share sheet, push-ready | Real risk remains for a thin wrapper; review notes should stress voice, memory, routines |
| Admin-looking buttons in Tools (Rent, Computer, Detect, Download) | Visible to everyone live | Recommend hiding them in the app builds (needs mockup OK) |
| Family/child profiles vs 18+ rating | Conflict | Decide: hide child profiles in store builds, or rate lower with stronger moderation (Apple Kids/COPPA rules then apply) |
| Play target API | targetSdk 36 ✔ | none |
| Play closed test (personal accounts made after Nov 13 2023) | Confirmed current: ≥12 testers opted in continuously for 14 days before production access | Joseph's ToDo: recruit ~14 testers' Gmail addresses |
| Package ID | New `com.simkosi.app`. The older native Simko SI app kit uses `com.simkosi.simcosi` | Confirm; IDs can't be changed after first upload |
| Supabase sign-in hook | Sends email on signup/signin events when enabled (disabled live). Deletion doesn't purge those rows | Fix before enabling it |
