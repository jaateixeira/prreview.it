"""Internal documents served as they are (Markdown), one source for team and plugin authors.

Only files named here are served; there is no directory lookup.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

PACKAGE = Path(__file__).resolve().parents[2]  # .../previewit
REPO = PACKAGE.parents[1]

# Where each served document lives: packaged in the wheel, or docs/ in a source checkout.
DOCUMENTS: dict[str, tuple[Path, Path]] = {
    "glossary.md": (PACKAGE / "internal_docs" / "glossary.md", REPO / "docs" / "glossary.md"),
}


@cache
def _read(name: str) -> str:
    for candidate in DOCUMENTS[name]:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError(name)


def build_docs_router() -> APIRouter:
    router = APIRouter()

    @router.get("/docs/internal/{name}")
    async def internal_doc(name: str) -> Response:
        if name not in DOCUMENTS:
            raise HTTPException(status_code=404)
        try:
            text = _read(name)
        except FileNotFoundError:
            raise HTTPException(status_code=404) from None
        return Response(
            text,
            media_type="text/markdown; charset=utf-8",
            headers={"Cache-Control": "public, max-age=300"},
        )

    return router
