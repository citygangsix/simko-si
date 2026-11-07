# Button audit

Clicked signed out and signed in at 390×844 and 1280×800 (`node tests/buttons.mjs`), with a mock Grok. Also checked a saved session: valid token, stale `sessionStorage` plus a valid cookie, and a fully stale token.

| button | what it does | result | fix made |
| --- | --- | --- | --- |
| Sign in (header) | Opens the sign-in box | works | Inline click handler so a cached script cannot leave it dead. A real session replaces it with the email. |
| Email (header) | Shows the signed-in address, shortened | works | Header now follows `/api/auth` `me`, including a valid cookie when `sessionStorage` is stale. |
| Sign out (header) | Ends the session and shows Sign in | works | |
| Sign in / Create account tabs | Switch the box | works | |
| Create account / Sign in submit | Posts `/api/auth` signup or signin | works | |
| Forgot password? | Opens the reset form | works | |
| Update password | Asks for a reset code, then sets the new password | works | Dev mode fills the code on screen when there is no mail server. |
| Back to sign in | Returns from reset to the sign-in form | works | |
| Close X | Closes the box | works | |
| Sign up / Sign in (tools drawer) | Open the same box | works | |
| Reset password (tools drawer) | Opens the reset form | works | |
| Sign out (tools drawer) | Same as the header sign out | works | Shown only while signed in. |
| Confirm email (tools drawer) | Would confirm a code | hidden | Not shown. Sign-up already starts the session. An empty confirm no longer writes “Confirm failed.” into the chat. |
| Set password (tools drawer) | Old reset control | hidden | Reset lives in the sign-in box. |
| New Chat | Starts a chat, or opens sign-in | works | |
| Search | Shows the search field and filters the list | works | |
| Send to chat | Opens sign-in, or the relay picker | works | |
| Relay Send | Copies the typed line into the other chat | works | |
| Chat list item | Opens that conversation | works | A demo id is no longer sent to `/api/sessions` after sign-in (that was a 404). |
| Back | Returns to the chat list on a phone | works | |
| Tools | Opens and closes the tools drawer | works | |
| Send | Sends the line, or asks you to type, or opens sign-in | works | Empty Send says “Type a message, then Send.” |
| Mic | Listens, or explains that the mic did not start | works | Signed-out preview does not call TTS (that was a 401). |
| Speaker on a reply | Plays that reply with the chosen sea-creature voice | works | Stays visible on every assistant reply (class `is-shown`, not the `hidden` attribute). Browser voice if TTS audio fails. |
| Voice name | Selects that sea-creature voice | works | |
| Voice play | Previews the voice | works | |
| Speed / Normal | Changes and resets speech speed | works | |
| Theme Reef / Plain | Switches the theme | works | |
| Lifebook area | Tags the latest line, or asks you to sign in | works | “Nothing to tag yet” is a normal response, not an HTTP error. |
| Lifebook disclosure | Opens the life areas | works | |
| Counts disclosure | Shows the counts | works | |
| Coding | Hides the gallery and shows the conversation | works | |
| Video / Image | Shows the turtle gallery | works | |
| Detect | Reads this browser and names a stack | works | |
| Download | Says the desktop app is not published yet | shows message | “Desktop app download coming soon.” |
| Advanced | Explains that advanced tools stay in the desktop app | shows message | |
| What renting would do | Explains GPU rental and that this site does not order one | shows message | |
| Confirm Rent | Says rent is off on the website | shows message | “Confirm Rent is turned off on the website…” |
| Cloud / Local / Rent | Old compute-mode labels | hidden | They do not apply on the website. Grok is always the brain. |
| Sea turtle | Opens the turtle screen | works | |
| Re-detect this computer | Runs the browser probe | works | |
| Run setup check | Says install happens in the desktop app | shows message | |
| Ask the turtle Send | Needs a question; signed out, opens sign-in | works | |
| Computer / Connect | Says this website already talks to Grok here | shows message | |
| Open chat (turtle screen) | Would dismiss the screen | hidden | “Look at the chats” already does that. |
| Look at the chats | Closes the turtle screen | works | |
| Raw | Opens the note that there is no separate raw transcript | shows message | The disclosure used to be `display: none` until it was already open, so it could not be clicked. |
