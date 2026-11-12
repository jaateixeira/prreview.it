# Architecture

Hexagonal modular monolith ([ADR 0001](../adr/0001-hexagonal-modular-monolith.md)): one deployable, strict layers. Imports point downward only; `make layers` enforces it.

```mermaid
flowchart TB
    BR(["Browser: HTML pages and HTMX fragments"])

    subgraph bootstrap ["bootstrap: composition root (built)"]
        B["create_app: wires adapters to ports"]
    end

    subgraph adapters ["adapters"]
        WEB["web: FastAPI, Jinja2, HTMX (skeleton built)"]
        PERS["persistence: SQLAlchemy, Alembic (M1)"]
        STOR["storage: files (M2)"]
        AUTH["auth: sessions, later OIDC and LTI (M1, M9)"]
        NOTIFY["notify: email, in-app (M6)"]
        PAY["billing: payment (M8)"]
    end

    subgraph application ["application: use cases and ports (planned)"]
        UCS["Use cases: commands and queries"]
        PORTS["Ports: repositories, FileStorage, AuthProvider, Notifier, Entitlements"]
    end

    subgraph domain ["domain: pure Python"]
        DOM["Party and AnonymityPolicy (built); entities, allocation, IdentityMask (planned)"]
    end

    subgraph plugins ["plugins: pluggy registry (M2)"]
        PL["ArtifactType, AllocationStrategy, CriterionType, Exporter, Notifier, AuthProvider"]
    end

    BR --> WEB
    B --> WEB
    WEB --> UCS
    UCS --> DOM
    UCS --> PORTS
    UCS --> PL
    PERS -. implements .-> PORTS
    STOR -. implements .-> PORTS
    AUTH -. implements .-> PORTS
    NOTIFY -. implements .-> PORTS
    PAY -. implements .-> PORTS
```

## Rules the diagram encodes

| Rule | Where |
|---|---|
| `domain` and `application` import no FastAPI, Jinja2, SQLAlchemy or I/O | `pyproject.toml`, import-linter |
| The server returns HTML; no JSON API, no SPA | [ADR 0002](../adr/0002-hypermedia-htmx.md) |
| The core never imports a plugin; it asks the registry | `PLAN.md` section 3 |
| Limits (50 MB, 100 shares) go through the `Entitlements` port | `CLAUDE.md` |
| Only `IdentityMask` turns a Party into a display name | `PLAN.md` section 2.2 |
| Built-in text and PDF types are plugins too | `PLAN.md` section 1 |

## Source layout

```
src/previewit/
  bootstrap.py     composition root
  domain/          party.py, anonymity.py
  application/     (empty)
  adapters/web/    app.py, templates/, static/
  plugins/         (empty)
tests/             unit, integration, acceptance
```
