# Age rating answers

Answers for what this build does. The app shows no built-in content of its own. It shows replies from a local Granite model on the user's own computer, and that model can produce open-ended text.

Store questionnaires change wording from time to time. If a question below reads differently in the form, pick the answer that matches the facts in the right-hand column.

## Apple (App Store Connect → App Information → Age Rating)

| Question | Answer | Why |
| --- | --- | --- |
| Cartoon or fantasy violence | None | No such built-in content |
| Realistic violence | None | — |
| Prolonged graphic or sadistic violence | None | — |
| Profanity or crude humor | Infrequent/Mild | Model replies are open-ended text |
| Mature or suggestive themes | Infrequent/Mild | Model replies are open-ended text |
| Horror or fear themes | None | — |
| Medical or treatment information | None | Not a medical app |
| Alcohol, tobacco, or drug use or references | None | — |
| Simulated gambling | None | — |
| Sexual content or nudity | None | — |
| Graphic sexual content and nudity | None | — |
| Contests | No | — |
| Unrestricted web access | No | The app talks only to the address the user entered. It has no browser. |
| User-generated content shared with other users | No | Chats are private between the user and their own computer |
| Messaging and chat with other people | No | Chat is with the user's own assistant, not other people |
| Advertising | No | — |
| Gambling (real money) | No | — |
| Made for Kids | No | — |

Expected result: **13+** (the bracket formerly shown as 12+), because of the "Infrequent/Mild" answers for model output. If Joseph wants 4+, every content row has to be None, and that is hard to justify for an open-ended model.

## Google Play (IARC questionnaire, Policy → App content → Content rating)

| Step or question | Answer |
| --- | --- |
| Category | All Other App Types (a utility or productivity app, not a game, social, or reference app) |
| Violence | No |
| Fear | No |
| Sexuality | No |
| Gambling | No |
| Language: crude humor or profanity | No built-in content. If the form asks about AI or generated text, answer "Yes, could contain mild language" |
| Controlled substances | No |
| Users can interact or exchange content with other users | No |
| Shares the user's current physical location with other users | No |
| Allows users to purchase digital goods | No |
| Unrestricted internet access (web browser or search engine) | No |
| Is the app a news or educational app | No |
| Generative AI | Yes. The app shows text from a model running on the user's own computer. Content is not moderated by a Simco server. |

Expected result: around **Teen / PEGI 12 / USK 12**. Play's AI-generated content policy asks for an in-app way to report offensive output. Today the app has no such button. See the owner checklist in `OWNER-CHECKLIST.md`.

## Target audience (Play → App content → Target audience)

- Age groups: 18 and over (16 to 17 is also acceptable). Do **not** select any under-13 group, which would put the app under the Families policy.
- Appeals to children: No.
