"""FastAPI application factory for the web adapter."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).parent


def build_app() -> FastAPI:
    app = FastAPI(title="Previewit", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "home.html", {"page_title": "Previewit"})

    @app.get("/fragments/status", response_class=HTMLResponse)
    async def status_fragment(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "fragments/status.html", {})

    @app.get("/healthz", response_class=PlainTextResponse)
    async def healthz() -> str:
        return "ok"

    return app
