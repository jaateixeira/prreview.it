# ADR 0008: Email verification
- Status: accepted
- Date: 2026-11-12

## Context
Password sign-ups start unverified (ADR 0007). Account linking and later features (invites, review by link) need to know an address is really the user's.

## Decision
- **Random, single-use, expiring tokens**: 256-bit random, valid 24 hours, only the SHA-256 hash is stored. A database leak does not yield usable links.
- **Bound to the address** it was issued for. If the account email changes, old links verify nothing.
- **The link opens a confirmation page; a POST (with CSRF) consumes it.** Mail scanners and link prefetchers issue GETs and must not burn the token.
- **Atomic consume**: one conditional `UPDATE ... WHERE unused AND unexpired`, so two concurrent clicks cannot both succeed.
- **Newest link only**: sending a new mail deletes older tokens. Resend is limited to one per 60 seconds per user.
- **Works without a session**: the link can be confirmed in another browser or on a phone.
- **Soft gate for now**: unverified users can use the app; features that need a verified address check `email_verified` when they arrive.
- **Mail behind a `Mailer` port**: SMTP adapter for hosting; a logging mailer in development prints the link to the server log. https deployments refuse to start without SMTP settings.
- A failing mail server never blocks sign-up; the account page offers "Resend".

## Consequences
- A 6-digit code flow, magic-link login and bounce handling are possible later without changing the token store.
- No per-IP rate limiting yet (planned with M8); the per-user cooldown only limits mail volume per account.
- Provider-verified emails (Google, Apple, HAKA within the home organisation) are verified at login and need no mail.
