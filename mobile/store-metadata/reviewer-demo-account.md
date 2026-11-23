# Reviewer demo account (PROPOSAL, nothing created)

Why: Apple (guideline 2.1) and Google both need a working login. Today a new account gets "Grok is not enabled for this account." on every message (owner lock in api/bootstrap.php, `simko_require_grok_owner`). Reviewers who see that will reject for 2.1 (app completeness) / 4.2 (minimum functionality), and Play will flag it as broken functionality.

Proposal (each step needs Joseph's OK; none done):
1. Create **review@simkosi.com** (or a Gmail like simkosi.review@gmail.com) as a normal Simko SI account; generate the password in the vault; give it to Apple/Google only in the review forms.
2. Add that one account to the Grok owner allowlist (server config `emails` list read by `simko_is_grok_owner`) so chat works. Daily budget still applies; set a review-period cap (for example $2/day) so a reviewer can't run up xAI cost.
3. Because reviewers may also make their own account: either (a) open Grok to everyone with a small free quota before submission, or (b) say clearly in the review notes "use the demo account; new sign-ups join a waitlist" and show a friendly waitlist screen instead of the raw error text. (a) is safer for approval.
4. Email confirmation: sign-up does not block on the confirm email (token issued immediately), so the missing DKIM/MX does not stop a reviewer from signing in. Password reset does depend on email, see blockers.
