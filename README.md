# Previewit

Fast, friendly, open-source peer review for any organization: classrooms, journals and conferences, engineering teams, companies.

Individuals and groups review each other (1:n and n:n), with configurable anonymity in each direction, multiple review rounds on revisions of the same work, and plugins for new kinds of artifacts (text and PDF today; code and more later).

Status: early development (M0 complete). Licensed under AGPL-3.0-or-later. See [docs/PLAN.md](docs/PLAN.md).

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
[AGPL-3.0-or-later](LICENSE). Run it yourself freely; if you offer a modified version as a network service, you must share your changes.
