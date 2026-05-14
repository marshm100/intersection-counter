from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from backend.config import FRONTEND_DIR
from backend.routers import (
    projects, video, videos, processing, dashboard,
    review, calibration, export, intersections,
)

app = FastAPI(title="Intersection Counter")

app.include_router(projects.router, prefix="/api")
app.include_router(video.router, prefix="/api")
app.include_router(videos.router, prefix="/api")
app.include_router(intersections.router, prefix="/api")
app.include_router(calibration.router, prefix="/api")
app.include_router(processing.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(export.router, prefix="/api")

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.get("/")
async def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="127.0.0.1", port=5000, reload=True)
