# Deployment manual

**Read first.** Self-hosting is for experts and is unsupported ([ADR 0005](../adr/0005-hosted-first-debian-only.md)). The easy path is the hosted site. There is no installer, no container image and no support for other systems.

**Status.** The application has sign-in (email and password, Google, Apple, HAKA), email verification, organizations, spaces, calls, submissions (text and PDF), rounds, reviews and invitations. Outgoing mail, the database and the cache are configurable. Quotas, payment and LTI are not built yet.

**Tested (2026-11-15):** the test suite on Python 3.13 with SQLite and PostgreSQL 16; the configuration file, the migration command and the start command against PostgreSQL 16. **Not tested:** the systemd unit, the nginx configuration and a real Debian 13 host (treat them as an outline to adapt), live Google, Apple, HAKA or SMTP, Valkey itself.

## 1. Requirements

| Item | Requirement |
|---|---|
| Operating system | Debian stable (13). Nothing else. |
| Python | Debian's `python3` (project needs 3.12 or newer) |
| Tools | `git`, `curl`, `uv` |
| Database | PostgreSQL. SQLite is for development only. |
| Cache | Valkey (recommended, optional): keeps the signed-in user close at hand. Required if you run more than one worker. |
| Front | nginx with TLS, or a tunnel that ends TLS and forwards to `127.0.0.1:8000` |
| Email | An SMTP relay. The application does not start on an https address without one. |
| Outbound web | DNS and outgoing HTTP and HTTPS (ports 80 and 443) to the internet: Previewit checks web pages before they go to reviewers (ADR 0022). It ignores proxy settings in the environment and refuses private addresses itself. |
| Hardware | Provisional: 4 CPU cores, 8 GB RAM, SSD storage. No load tests exist yet; figures will be set in M7. |
| Skills | Linux administration, systemd, nginx and TLS, PostgreSQL backup and restore, DNS, security patching |

## 2. Runtime view

```mermaid
flowchart LR
    U(["Browser"])
    M(["Moodle, LTI 1.3 (M9)"])
    subgraph srv ["Debian stable server"]
        N["nginx or tunnel: TLS"]
        A["previewit: uvicorn under systemd, 127.0.0.1:8000"]
        P[("PostgreSQL: data and uploaded files")]
        V[("Valkey: cached users, 60 s")]
    end
    SMTP(["SMTP relay"])
    IDP(["Google, Apple, HAKA"])
    U -- HTTPS --> N
    M -. LTI launch .-> N
    N -- HTTP --> A
    A --> P
    A -. optional .-> V
    A --> SMTP
    A --> IDP
```

Valkey is a copy, never the source of truth. If it is down the site is slower, not broken.

## 3. Install

```bash
sudo apt-get update
sudo apt-get install -y python3 git curl ca-certificates postgresql valkey
sudo adduser --system --group --home /opt/previewit previewit
sudo -u previewit -H sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u previewit -H git clone https://github.com/jaateixeira/prreview.it /opt/previewit/app
cd /opt/previewit/app
sudo -u previewit -H env UV_PYTHON_PREFERENCE=only-system \
  /opt/previewit/.local/bin/uv sync --frozen --no-dev --extra postgres --extra valkey
```

`--frozen` installs exactly what `uv.lock` pins; `--no-dev` leaves out test tools. Add `--extra saml` for HAKA (needs `xmlsec1` from apt). If `apt` has no `valkey` package on your release, use another Redis-compatible server, or leave the cache out and run one worker. Bind it to `127.0.0.1` and set a password if anything else can reach it.

## 4. Database

```bash
sudo -u postgres createuser --pwprompt previewit
sudo -u postgres createdb --owner previewit previewit
```

## 5. Configure

Settings come from a TOML file and from `PREVIEWIT_*` environment variables; a variable overrides the file. The file is read from `PREVIEWIT_CONFIG`, else `./previewit.toml`, else `/etc/previewit/previewit.toml`.

```bash
sudo install -d -o previewit -g previewit -m 700 /etc/previewit
sudo install -o previewit -g previewit -m 600 previewit.example.toml /etc/previewit/previewit.toml
openssl rand -hex 32 | sudo install -o previewit -g previewit -m 600 /dev/stdin /etc/previewit/secret.key
sudoedit /etc/previewit/previewit.toml
```

Set at least these:

```toml
[server]
base_url = "https://review.example.org"   # exactly the address people type; no trailing slash
secret_key_file = "secret.key"
# aliases = ["https://www.review.example.org"]   # other names of this site (ADR 0021)

[database]
url = "postgresql+psycopg://previewit:PASSWORD@localhost/previewit"

[mail]
smtp_host = "smtp.example.org"
smtp_port = 587
smtp_user = "…"
smtp_password = "…"
smtp_security = "starttls"                 # or "ssl" for port 465
from = "Previewit <no-reply@review.example.org>"

[cache]
url = "valkey://127.0.0.1:6379/0"
```

| Other section | What it sets |
|---|---|
| `[logging]` | `level`: `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `[policy]` | `require_verified_email_for`: which actions need a verified email. Default: none, so invited reviewers can review without an account and join afterwards (ADR 0020). Listing `review` or `join` turns that off |
| `[login.google]`, `[login.apple]`, `[login.haka]` | providers, each on when configured ([`docs/auth/login-setup.md`](../auth/login-setup.md)) |
| `[ai]` | AI reviews (ADR 0025): `enabled` (default `true`), `ollama_url` of your own model server for the free models, `local_place` and `local_country` (shown with a flag), `local_context` (tokens, default 8192), `local_models` (offer only these). For reviews paid with credit (ADR 0026): `keys_file`, `margin_percent` (30), `usd_to_eur` ("1.00"), `fees_and_tax_percent` (40). See sections 8a and 8b |
| `[seller]` | Who runs and sells the site, shown on `/terms`, `/privacy`, `/contact` (ADR 0026): `legal_name`, `trading_name`, `business_id`, `address`, `email`, `phone`, `privacy_email`, `processors` |
| `[paddle]` | Selling credit (ADR 0026): `environment` (`sandbox` or `production`), `client_token`, `webhook_secret` or `webhook_secret_file`, `packs` (Paddle price id = whole euros). See section 8b |

The file holds secrets: keep it readable by the `previewit` account only (the server warns if group or others can read it). Typos in keys, sections or action names stop the server at start and name the setting. Forms are checked against `base_url`, so the site lives at that one address. List every other name that reaches the server under `aliases`: visitors who arrive there are sent to the same page at `base_url`. Each name needs DNS, a certificate and a place in the proxy (`server_name`) or tunnel.

## 6. Run

`/etc/systemd/system/previewit.service`:

```ini
[Unit]
Description=Previewit
After=network.target postgresql.service valkey.service

[Service]
User=previewit
Group=previewit
WorkingDirectory=/opt/previewit/app
ExecStartPre=/opt/previewit/app/.venv/bin/python -c "import os; from previewit.adapters.settings import load_settings; from previewit.adapters.persistence.migrate import upgrade; upgrade(load_settings(os.environ).database_url)"
ExecStart=/opt/previewit/app/.venv/bin/uvicorn previewit.bootstrap:create_app --factory --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
```

`ExecStartPre` brings the database to the latest schema before each start; PostgreSQL is never migrated by the application itself. Two workers need the `[cache]` url; without Valkey, remove `--workers 2`, or each worker keeps its own cache and the server warns at start.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now previewit
curl -s http://127.0.0.1:8000/healthz    # prints: ok
journalctl -u previewit -n 50            # if it does not
```

**Logs and console.** On start the service prints a summary (address, database kind, cache, mail, login methods, artifact types, policy; never a secret). Logs go to stderr, so `journalctl -u previewit -f` shows them. For debugging set `[logging] level = "DEBUG"`, or `TRACE` to see every cache hit and miss, and restart.

**A form is refused** ("Form refused" page, HTTP 403). The page says why, and the log has a line `Form refused on <path>: <reason>` (`journalctl -u previewit | grep "Form refused"`). The usual causes:

| The page says | Cause | Fix |
|---|---|---|
| opened at another address | The browser used a name or scheme other than `base_url`: `www.`, `http://`, a LAN or Tailscale address, or an alias missing from `[server] aliases` | Open the site at `base_url`; list every other public name in `aliases` so it redirects there |
| did not send the form cookie | Cookies blocked, or an https `base_url` reached over plain http | Allow cookies; reach the site over https |
| out of date | The page was opened before the browser's form cookie was renewed | Reload the page |

A development copy started with a production `base_url` (say, `make run` with `previewit.toml` from the server) refuses every form at `http://localhost:8000`: set `PREVIEWIT_BASE_URL=http://localhost:8000` for development.

## 7. Front: TLS and reverse proxy

**nginx.** `/etc/nginx/sites-available/previewit` (link it into `sites-enabled`):

```nginx
server {
    listen 80;
    server_name review.example.org;
    client_max_body_size 12m;     # PDF submissions: 10 MB file plus form fields

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo certbot --nginx -d review.example.org
```

The application also refuses bodies announcing more than 12 MB, but only the proxy can stop a request that does not announce its size, so keep `client_max_body_size`.

**The MCP service** (`/mcp`, ADR 0023) needs no account, so strangers can call it. The application allows 20 prepared requests per client address every 10 minutes in each worker; for a limit across workers, add one in nginx:

```nginx
limit_req_zone $binary_remote_addr zone=mcp:10m rate=30r/m;   # in the http block
location = /mcp {
    limit_req zone=mcp burst=20 nodelay;
    client_max_body_size 300k;
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

**Tunnel.** A tunnel that ends TLS at its provider (for example `cloudflared`) can replace nginx: point its public hostname at `http://127.0.0.1:8000`. It must run on the same host, or `--forwarded-allow-ips` must name the address it connects from.

## 8. Outgoing email

Previewit sends verification mails and invitations over SMTP only. Use a relay that signs for your domain, and publish its SPF, DKIM and DMARC records before the first invitation. Send yourself an invitation and check that the headers say `spf=pass` and `dkim=pass`.

## 8a. AI reviews and the free models

People can ask AI models to review their work (ADR 0025). The paid models run at their own services with the person's key; Previewit only passes the key on, for one request, and never stores it. The free models run on **your own** [Ollama](https://ollama.com) server. Without one, people see only the paid models.

Previewit's hosted site uses an AMD BC-250 board with 16 GB of shared memory. Small models (7 to 12 billion parameters) fit; one review of a short essay takes a few minutes. Previewit sends the free server one review at a time.

On the model server (Debian, on the same private network as Previewit):

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl edit ollama        # add: [Service] Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl restart ollama
ollama pull qwen3:8b              # and any others; embedding models are never offered
```

Let only the Previewit server reach port 11434 (a firewall rule or a private network): Ollama has no login. Then in `previewit.toml`:

```toml
[ai]
ollama_url = "http://10.0.0.7:11434"
local_place = "Finland"
local_country = "FI"
local_context = 8192                  # raise it if the board has memory to spare
# local_models = ["qwen3:8b"]         # offer only these
```

Previewit looks up the installed models every five minutes; if the server is off, the free models are simply not offered and the log says so once. Reviews are written in the background and survive nothing: after a restart, free reviews are queued again and keyed ones ask the person to try again. Free reviews are limited to ten a person a day.

The prices of the paid models are in `src/previewit/adapters/ai/models.toml`, with the date each was checked. They change often: check them every month. Set `enabled = false` to switch AI reviews off.

## 8b. Selling credit through Paddle

Paddle sells credit as merchant of record (ADR 0026); the step-by-step setup, sandbox first, is in [`docs/business/paddle-application.md`](../business/paddle-application.md). On the server:

- Paddle posts signed notifications to `https://<your site>/paddle/webhook`. The proxy must pass `POST` there with the body untouched; Previewit checks the signature against the raw bytes.
- The webhook secret and Previewit's own model keys are secrets: put them in files readable by the `previewit` account only (`webhook_secret_file`, `[ai] keys_file`, `chmod 600`). The keys file is TOML, one line per service: `anthropic = "sk-ant-…"`. A service without a key there can still be used with the person's own key.
- Without `[paddle]` the site sells nothing: the Pricing page says credit opens soon.

## 9. Backup

Submitted text and PDFs are stored **in PostgreSQL** (table `revisions`), so a database backup is the whole backup. AI reviews are in `ai_reviews`; no key is stored anywhere. Credit is in `credit_entries`; Paddle keeps the payments themselves. The table `prepared_requests` also holds files that visitors chose before signing in, for one hour (at most 200 at a time, 2 GB at the very most); the running site deletes them when they expire (ADR 0024). Dump regularly and test a restore. Valkey needs no backup; it only holds copies. Keep the configuration and the secret key with the dumps: with a new key, everyone is signed out.

```bash
sudo -u postgres pg_dump --format=custom previewit > previewit-$(date +%F).dump
sudo -u postgres pg_restore --clean --dbname previewit previewit-2026-11-15.dump
```

## 10. Update

```bash
cd /opt/previewit/app
sudo -u previewit -H git pull --ff-only
sudo -u previewit -H env UV_PYTHON_PREFERENCE=only-system \
  /opt/previewit/.local/bin/uv sync --frozen --no-dev --extra postgres --extra valkey
sudo systemctl restart previewit         # migrates, then starts
```

Take a dump first. Read the release notes; the plugin API is unstable until version 0.2.

## 11. Planned sections

| Topic | Milestone |
|---|---|
| Monitoring, logs, performance budgets | M7 |
| Quotas and payment (hosted mode only), separate file storage | M8 |
| LTI 1.3 registration in Moodle | M9 |

## 12. Licence duties

Previewit is AGPL-3.0-or-later. If you run a modified version for others over a network, you must offer them your source. The page footer links to `SOURCE_URL` in `src/previewit/adapters/web/app.py`; point it at your own repository if you change the code.
