# Previewit

Fast, friendly, open-source peer review for any organization: classrooms, journals and conferences, engineering teams, companies.

Individuals and groups review each other (1:n and n:n), with configurable anonymity in each direction, multiple review rounds on revisions of the same work, and plugins for new kinds of artifacts (text and PDF today; code and more later).

Status: early development (M0 complete). Licensed under AGPL-3.0-or-later. See [docs/PLAN.md](docs/PLAN.md) and [docs/business/](docs/business/README.md).

## Hosted or self-hosted
The easy way to use Previewit will be the hosted service, with a free tier (in preparation). Self-hosting is possible but unsupported and for experts only: Debian Linux (stable) and PostgreSQL, no container image or installer. See [ADR 0005](docs/adr/0005-hosted-first-debian-only.md).

## Documentation
| | |
|---|---|
| Plan and decisions | [docs/PLAN.md](docs/PLAN.md), [docs/adr/](docs/adr/), [docs/business/](docs/business/README.md) |
| UML diagrams | [docs/uml/](docs/uml/README.md) |
| Research | [Review designs across industries](docs/research/review-designs.md), [literature review](docs/research/peer-review-literature.md) |
| Manuals | [User manual](docs/manuals/user-manual.md), [Deployment manual](docs/manuals/deployment-manual.md) |

## Quick start
```bash
make install   # uv sync + Playwright browser
make run       # http://127.0.0.1:8000
make check     # lint, types, layering, all tests
```
Stack: Python, FastAPI, Jinja2, HTMX. Tests: pytest, hypothesis, Playwright.

## Contributing
See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and [SECURITY.md](SECURITY.md).

## Licence
[AGPL-3.0-or-later](LICENSE). If you offer a modified version as a network service, you must share your changes.
