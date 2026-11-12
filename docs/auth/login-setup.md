# Login setup

Settings come from an optional TOML file and from `PREVIEWIT_*` environment variables. A variable overrides the same setting in the file. Variable names below are the environment form; the file form is in [`previewit.example.toml`](../../previewit.example.toml).

## Configuration file

The file is read from `PREVIEWIT_CONFIG` (an error if it is missing), else `./previewit.toml`, else `/etc/previewit/previewit.toml`. With none of them, only environment variables apply.

```toml
[server]   # base_url, secret_key or secret_key_file
[database] # url
[mail]     # smtp_host, smtp_port, smtp_user, smtp_password, smtp_security, from
[policy]   # require_verified_email_for
[cache]    # url
[logging]  # level
[login.google] [login.apple] [login.haka]
```

- Unknown sections, keys, actions and wrong types stop the server at start, naming the setting.
- Relative file paths (`secret_key_file`, `private_key_file`, HAKA certificates) are relative to the config file.
- If the file holds secrets and is readable by group or others, the server logs a warning: `chmod 600` it.

### Email verification policy

Which actions need a verified email address:

```toml
[policy]
require_verified_email_for = ["review"]   # the default
```

| Action | Gate |
|---|---|
| `create_organization` | Creating an organization. |
| `invite` | Creating invitation links. |
| `join` | Joining a space through a link. A refused attempt does not use up the link. |
| `submit` | Submitting work (enforced from M2). |
| `review` | Writing a review (enforced from M2). |

Signing in and receiving invitations are never gated. `[]` requires nothing; the same via the environment is `PREVIEWIT_REQUIRE_VERIFIED_EMAIL_FOR="review,submit"` (empty string for none).

Email + password works with no configuration. Google, Apple and HAKA switch on when their variables are set. Setting only some of a provider's variables stops the server at startup and names what is missing.

## Cache and logging

| Variable | Default | Notes |
|---|---|---|
| `PREVIEWIT_CACHE_URL` | none | `valkey://host:6379/0` (also `redis://`, `rediss://`). Unset: an in-process cache. May contain a password, so keep the config file `chmod 600`. |
| `PREVIEWIT_LOG_LEVEL` | `INFO` | `TRACE` (every cache hit and miss), `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

**Valkey** keeps a copy of the signed-in user for 60 seconds, because every request with a session cookie looks the user up. Changes (email verified, password, linked login) drop the copy at once. Valkey holds no secrets (never password hashes) and is never the source of truth: if it is down the site is slightly slower, not broken. Install the client with `uv sync --extra valkey` (`make install` already does). On Debian: `apt install valkey` (or a Redis-compatible server), bind it to localhost, and set a password if it is reachable from anywhere else.

Run **one worker without Valkey**, or several workers **with** it: each worker's in-process cache is separate, so another worker could show an out-of-date user for up to 60 seconds. The server warns at start when `WEB_CONCURRENCY` is above 1 and no cache URL is set.

**Logs** go to stderr through loguru, colourised on a terminal; uvicorn, SQLAlchemy and library logs are captured into the same stream. The start-up summary on stdout (address, database, cache, mail, login methods, plugins, policy) is drawn with rich and never prints a secret. For debugging use `PREVIEWIT_LOG_LEVEL=DEBUG`; `TRACE` adds per-request detail.

## Core

| Variable | Default | Notes |
|---|---|---|
| `PREVIEWIT_SECRET_KEY` | random per process (http only) | Required when the base URL is https. Signs session cookies. |
| `PREVIEWIT_BASE_URL` | `http://localhost:8000` | Public URL, no trailing slash. https turns on `Secure` cookies. Also the allowed `Origin` for form posts. |
| `PREVIEWIT_DATABASE_URL` | `sqlite:///previewit.db` | SQLite is migrated automatically at start. For PostgreSQL run the migration yourself (below). |

PostgreSQL: `uv run python -c "from previewit.adapters.persistence.migrate import upgrade; upgrade('postgresql+psycopg://...')"` (install the driver with `uv sync --extra postgres`).

## Google

1. Google Cloud Console, create an OAuth client of type *Web application*.
2. Authorised redirect URI: `<BASE_URL>/auth/google/callback`.
3. Set `PREVIEWIT_GOOGLE_CLIENT_ID` and `PREVIEWIT_GOOGLE_CLIENT_SECRET`.

Local testing works with `http://localhost:8000` as the base URL.

## Apple

Needs a paid Apple Developer account, https and a real domain (no localhost).

1. Create an App ID with *Sign in with Apple*, then a **Services ID** (this is the client id).
2. On the Services ID add your domain and the return URL `<BASE_URL>/auth/apple/callback`.
3. Create a *Sign in with Apple* key; download the `.p8` once and note the Key ID. Note your Team ID.
4. Set `PREVIEWIT_APPLE_CLIENT_ID` (Services ID), `PREVIEWIT_APPLE_TEAM_ID`, `PREVIEWIT_APPLE_KEY_ID` and either `PREVIEWIT_APPLE_PRIVATE_KEY_FILE=/path/AuthKey.p8` or `PREVIEWIT_APPLE_PRIVATE_KEY` (PEM, `\n` allowed for newlines).

Apple sends the user's name only on the first sign-in. Users who hide their email get a relay address.

## HAKA

Install the extra and the system package: `uv sync --extra saml` and `apt install xmlsec1` (Debian).

1. Make a service key pair (self-signed is normal in SAML): `openssl req -x509 -newkey rsa:3072 -nodes -days 3650 -keyout sp.key -out sp.crt -subj "/CN=<your domain>"`.
2. Choose the service entity id (any stable URL you own, for example `<BASE_URL>/saml/sp`).
3. Start the app with the variables below and open `<BASE_URL>/auth/haka/metadata`; this is the SP metadata XML to register.
4. Register the service in the Haka Resource Registry (CSC). Production requires approval and follows Haka's certificate and attribute policies. Test first with the Haka test IdP.
5. Download Haka's metadata signing certificate from the federation's page and set it as `PREVIEWIT_HAKA_METADATA_CERT`. Metadata fetched from a URL is refused without it.

| Variable | Meaning |
|---|---|
| `PREVIEWIT_HAKA_ENTITY_ID` | Service entity id from step 2. |
| `PREVIEWIT_HAKA_CERT_FILE`, `PREVIEWIT_HAKA_KEY_FILE` | The key pair from step 1. |
| `PREVIEWIT_HAKA_METADATA_URL`, `PREVIEWIT_HAKA_METADATA_CERT` | Federation metadata and the certificate that signs it. |
| `PREVIEWIT_HAKA_METADATA_FILE` | Local metadata instead of (or besides) the URL, for a single IdP. |
| `PREVIEWIT_HAKA_DISCOVERY_URL` | Haka discovery service, so users pick their university. |
| `PREVIEWIT_HAKA_IDP_ENTITY_ID` | Skip discovery and always use this IdP (the Haka test IdP). |

The SAML ACS endpoint is `<BASE_URL>/auth/haka/callback` (HTTP-POST). Attributes the service uses: `eduPersonUniqueId` (preferred), persistent NameID, `eduPersonPrincipalName`, `mail`, `schacHomeOrganization`, `displayName`/`cn`. Ask for these when registering.

Metadata is loaded on the first HAKA login, not at startup, so a metadata outage cannot stop the site.

## Status of verification

Tested without the real providers: claim mapping, Apple client-secret JWT, a signed SAML round trip against a local identity provider, and the web flows with a fake provider. **Not yet exercised against live Google, Apple or Haka.** Do that with test accounts before announcing the feature.

## Email (verification)

Verification mails need a mail server. https deployments will not start without one.

| Variable | Default | Meaning |
|---|---|---|
| `PREVIEWIT_SMTP_HOST` | none | SMTP server. Unset in development: the mail, including the link, is written to the server log. |
| `PREVIEWIT_SMTP_PORT` | `587` | |
| `PREVIEWIT_SMTP_SECURITY` | `starttls` | `starttls`, `ssl` (usually port 465) or `none`. |
| `PREVIEWIT_SMTP_USER`, `PREVIEWIT_SMTP_PASSWORD` | none | Optional login. |
| `PREVIEWIT_MAIL_FROM` | none | Required with a host, for example `Previewit <no-reply@your-domain>`. |

Set up SPF, DKIM and DMARC for the sending domain, or verification mails will land in spam. Run `upgrade()` (see Core) after updating: migration 0002 adds the token table.
