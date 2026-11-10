# Contributing to Previewit

Thanks for helping! Previewit is licensed under **AGPL-3.0-or-later**; by contributing you agree your work is released under the same licence. Please sign off commits (`git commit -s`) to certify the [Developer Certificate of Origin](https://developercertificate.org/).

## Getting started
```bash
make install   # uv sync + Playwright browser
make check     # lint, types, layering, all tests (must pass before a PR)
make run       # http://127.0.0.1:8000
make hooks     # optional: pre-commit hooks (ruff, layering)
```
Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). Read `docs/PLAN.md` and `CLAUDE.md` for the architecture rules.

## Ground rules
- **Layering is enforced:** `bootstrap > adapters > application > domain`. `domain/` and `application/` never import web or database frameworks.
- **Domain-neutral language:** use Space / Member / Party / Call / Submission / Review in core code. Education wording belongs in presets.
- **Test first.** Unit tests for domain logic (use `hypothesis` for invariants), integration tests for adapters, a Playwright acceptance test for user-visible features.
- **Hypermedia, not SPA:** return HTML fragments for HTMX; keep JS small.
- **Decisions are recorded** as ADRs in `docs/adr/`.
- Conventional commit messages (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).

## Pull requests
Small and focused. Link the issue, describe the change, include tests, and make sure CI is green. A maintainer will review; please be patient and kind.

## Writing a plugin
The plugin API (artifact types, allocation strategies, exporters, …) is **unstable until v0.2**. Open an issue first so we can shape it together.

## Reporting security issues
See [SECURITY.md](SECURITY.md); please do not open public issues for vulnerabilities.
