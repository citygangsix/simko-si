# Google Play data safety answers (and Apple privacy labels)

These answers describe the current build. Play counts any data the app sends off the phone as "collected," even when it goes to the user's own computer. So answer **Yes, collected**, then show that nothing is shared.

## Play Console → App content → Data safety

### Overview

| Question | Answer |
| --- | --- |
| Does your app collect or share any of the required user data types? | **Yes** |
| Is all of the user data collected by your app encrypted in transit? | **No.** Traffic is HTTPS when the user enters an https address. A plain http address on a home network is not encrypted. |
| Which account creation methods does your app support? | **None** handled by the developer. Optional sign-in goes to the user's own computer. If the form requires a choice, pick "Username and password" and see the deletion note below. |
| Do you provide a way for users to request that their data is deleted? | **Yes.** Deleting the app clears the saved address and settings. Data on the user's computer is deleted on that computer. Explain this in the delete-account URL page (see `OWNER-CHECKLIST.md`). |

### Data types

| Category → type | Collected | Shared | Processed ephemerally | Required or optional | Purposes |
| --- | --- | --- | --- | --- | --- |
| Personal info → Email address | Yes | No | No | Optional (sign-in only) | App functionality, Account management |
| Messages → Other in-app messages (chat text) | Yes | No | No | Required to use chat | App functionality |
| App activity → Other user-generated content (Lifebook notes, translator text) | Yes | No | No | Optional | App functionality |

Answer **Not collected** for everything else: location, financial info, health and fitness, photos and videos, audio, files and docs, calendar, contacts, web browsing, app info and performance (crash logs, diagnostics), and device or other IDs.

### Security practices section (shown on the listing)

- Data is encrypted in transit: **No**. See above. Do not claim Yes while http addresses are allowed.
- You can request that data be deleted: **Yes**.
- Committed to Play Families Policy: **No** (not a kids' app).
- Independent security review: **No**.

### Other App content forms

| Form | Answer |
| --- | --- |
| Ads | No, the app does not contain ads |
| App access | All or some functionality is restricted. Provide reviewer instructions with a reachable Simco SI host address, or explain that a host is required and attach a demo video. |
| Government app | No |
| Financial features | None |
| Health | None |
| News app | No |
| COVID-19 | Not a contact tracing or status app |

## Apple App Privacy (App Store Connect → App Privacy)

| Question | Answer |
| --- | --- |
| Do you or your third-party partners collect data from this app? | **Yes** (Apple counts data sent to any server, including the user's own) |
| Contact Info → Email Address | Collected. Used for App Functionality. Not linked to the user's identity by the developer. Not used for tracking. |
| User Content → Other User Content (chat messages, notes) | Collected. Used for App Functionality. Not linked to identity. Not used for tracking. |
| Everything else | Not collected |
| Tracking (App Tracking Transparency) | **No.** The app does not track, so no ATT prompt is needed. |

If Joseph prefers to argue "data goes only to the user's own server, so it is not collected by the developer," both stores may accept "No data collected." The answers above are the conservative choice that avoids a policy rejection.
