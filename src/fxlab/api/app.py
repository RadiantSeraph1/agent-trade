from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fxlab import __version__
from fxlab.api.auth import make_current_user
from fxlab.config import Settings

def _find_web_dir() -> Path:
    for c in (os.environ.get("FXLAB_WEB_DIR"), Path.cwd() / "web", Path(__file__).resolve().parents[3] / "web"):
        if c and (Path(c) / "index.html").is_file():
            return Path(c).resolve()
    raise RuntimeError("web directory not found; set FXLAB_WEB_DIR")


WEB_DIR = _find_web_dir()


def create_app(settings: Settings | None = None, verify=None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="fxlab", docs_url=None, redoc_url=None, openapi_url=None)
    current_user = make_current_user(settings, verify) if verify else make_current_user(settings)

    @app.get("/api/health")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/api/status")
    def status(user: str = Depends(current_user)) -> dict:
        return {
            "version": __version__,
            "user": user,
            "mode": "paper / demo only",
            "data_source": "none connected",
            "ai_mode": settings.ai_mode.value,
            "ai_kill_switch": settings.ai_kill_switch,
            "risk_config_version": settings.risk.version(),
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/sw.js")
    def sw() -> FileResponse:
        # Served from root so the worker scope covers the whole app; never cached.
        return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})

    @app.middleware("http")
    async def security_headers(request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    app.mount("/", StaticFiles(directory=WEB_DIR), name="web")
    return app


app = None  # created lazily by the ASGI factory: uvicorn fxlab.api.app:create_app --factory
