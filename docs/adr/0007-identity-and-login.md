# ADR 0007: Identity and login (Google, Apple, HAKA, email + password)
- Status: accepted
- Date: 2026-11-12

## Context
Hosted-first (ADR 0005) means sign-up to first review must be fast, and the Education beachhead means Finnish universities log in through HAKA (SAML, run by CSC). Students expect "Continue with Google/Apple".

## Decision
- **Users are global**, not tenant-owned. Organization membership (and `org_id` on owned rows) arrives with the rest of M1.
- **One identity model.** `User` plus `ExternalIdentity(provider, subject)`. Providers are `google`, `apple`, `haka`; email + password is a built-in credential, not a provider.
- **Provider port** (`adapters/auth/base.py`): `begin(request, redirect_uri)` and `complete(request) -> ExternalClaims`. Everything after the claims is pure domain/application code.
- **Account linking is a pure policy** (`domain/identity.py: decide_external_login`):
  - a known identity signs in;
  - a *provider-verified* email equal to an existing account's email links to it; if that account never verified its email, its password is dropped ("claim by verification", so pre-registering someone's address gives no access);
  - otherwise a new user is created, and an *unverified* email is never stored.
- **Passwords**: Argon2id, length 10-128 and no composition rules. Sign-ups start unverified; the email-verification flow comes with the notification adapter (M6).
- **Sessions**: our own signed, HttpOnly, SameSite=Lax cookie (14 days). OAuth/SAML flow state lives in a separate short-lived cookie (`pv_flow`, path `/auth`; SameSite=None+Secure on https because Apple and SAML answer with a cross-site POST).
- **CSRF**: double-submit cookie plus an Origin check on every form POST. Auth forms are plain POSTs (htmx ignores 4xx responses, so boosted forms hide errors).
- **HAKA**: direct SAML with pysaml2 (optional extra `saml`, needs the `xmlsec1` package), no broker. Subject is `{idp entity id}!{eduPersonUniqueId | persistent NameID | ePPN}`. A mail address counts as verified only if its domain is within `schacHomeOrganization`.
- **Google/Apple**: OpenID Connect through Authlib. Apple's client secret is an ES256 JWT regenerated before each token exchange.

## Consequences
- Contributors can develop without any provider: only the password flow is on by default. Providers switch on from environment variables (`docs/auth/login-setup.md`).
- HAKA needs registration of the service in the Haka Resource Registry (CSC approval), so it cannot go live before the domain exists. Google and Apple need developer accounts (Apple is paid) and https.
- Real providers are tested with fakes, claim-mapping unit tests, a signed-JWT check for Apple and a local SAML IdP round trip for HAKA. Nothing is verified against live Google, Apple or Haka yet.
- Known accepted risk: sign-up reveals whether an email is taken. Rate limiting arrives with the hosted-service work (M8).
- Sessions are stateless: logout clears the cookie but cannot revoke a stolen one before expiry. Revisit with server-side sessions if needed.
