import subprocess
from datetime import datetime, timezone

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from backend.config import APP_DIR, FRONTEND_DIR
from backend.routers import (
    projects, video, videos, processing, dashboard,
    review, calibration, export, intersections, qa,
)


def _git_head() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(APP_DIR),
            stderr=subprocess.DEVNULL, text=True,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


_GIT_HEAD = _git_head()
_BOOT_TIME = datetime.now(timezone.utc).isoformat()
_ASSET_VERSION = _BOOT_TIME.replace(":", "").replace("-", "").replace(".", "")[:14]


app = FastAPI(title="Intersection Counter")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Disable browser caching on /static/* so JS/CSS edits show up on refresh.
    This is a localhost dev tool — bandwidth is irrelevant, stale UI is painful."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


app.include_router(projects.router, prefix="/api")
app.include_router(video.router, prefix="/api")
app.include_router(videos.router, prefix="/api")
app.include_router(intersections.router, prefix="/api")
app.include_router(calibration.router, prefix="/api")
app.include_router(processing.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(qa.router, prefix="/api")

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
async def root():
    """Inject a per-boot version into asset URLs so browsers fetch fresh JS/CSS
    after a restart instead of serving stale cached copies."""
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        '.js"></script>', f'.js?v={_ASSET_VERSION}"></script>'
    ).replace(
        'styles.css"', f'styles.css?v={_ASSET_VERSION}"'
    )
    return HTMLResponse(content=html)

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/api/health")
async def health():
    return {"status": "ok"}

@app.get("/api/version")
async def version():
    return {"commit": _GIT_HEAD, "booted_at": _BOOT_TIME}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=5000, reload=True)
