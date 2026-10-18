"""HTTP API: upload drone videos and expose the latest glasses alert."""
import asyncio
import os
import tempfile
from pathlib import Path

import cv2
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from firesight.alerts import validate_alert
from firesight.video import analyze_video

app = FastAPI(title="FireSight API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

latest_alert = None
alert_lock = asyncio.Lock()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/latest")
async def get_latest():
    async with alert_lock:
        if latest_alert is None:
            return Response(status_code=204)
        return JSONResponse(content=latest_alert)


@app.post("/latest")
async def publish_latest(payload: dict):
    """Publish a prebuilt alert (handy for frontend integration and mock data)."""
    global latest_alert
    try:
        alert = validate_alert(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    async with alert_lock:
        latest_alert = alert
    return JSONResponse(content=alert)


@app.post("/video")
async def upload_video(video: UploadFile = File(...), sample_seconds: float = 1.0):
    """Analyze an uploaded video, publish the resulting alert, and return it."""
    global latest_alert
    suffix = Path(video.filename or "drone-video.mp4").suffix or ".mp4"
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
            while chunk := await video.read(1024 * 1024):
                temp_file.write(chunk)
        alert = await asyncio.to_thread(analyze_video, temp_path, sample_seconds)
    except (OSError, ValueError, cv2.error) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        await video.close()
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
    async with alert_lock:
        latest_alert = alert
    return JSONResponse(content=alert)
