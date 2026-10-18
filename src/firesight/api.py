"""HTTP API: upload drone videos and expose the latest glasses alert."""
import asyncio
from contextlib import asynccontextmanager, suppress
from firesight.live import BundleWatcher, RemoteBeagleWatcher, timestamp
import time
import hmac
from datetime import datetime, timezone
from pydantic import BaseModel, Field
import os
import tempfile
from pathlib import Path

import cv2
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from firesight.alerts import validate_alert
from firesight.mapview import render_map
from firesight.frame import SUPPORTED_IMAGE_TYPES, analyze_frame
from firesight.gemini import GeminiConfigurationError, GeminiRequestError
from firesight.video import analyze_video

async def publish_live(alert):
    global latest_alert
    async with alert_lock:
        latest_alert = alert


@asynccontextmanager
async def lifespan(app):
    app.state.watcher = (RemoteBeagleWatcher(os.environ["BEAGLE_URL"], os.getenv("BEAGLE_EXPORT_TOKEN", ""), analyze_frame, publish_live, frame_lock)
                         if os.getenv("BEAGLE_URL") else BundleWatcher(os.getenv("FRAME_DIR"), analyze_frame, publish_live, frame_lock))
    task = asyncio.create_task(app.state.watcher.run())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="FireSight API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def protect_public_writes(request: Request, call_next):
    if os.getenv("PUBLIC_DEPLOYMENT") == "true" and request.method == "POST" and request.url.path in ("/frame", "/video", "/latest"):
        token = os.getenv("INGEST_TOKEN", "")
        if not token or not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            return JSONResponse({"detail": "A valid ingest token is required"}, status_code=401)
        # Enforce a bounded request body, including chunked requests.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 15 * 1024 * 1024:
                return JSONResponse({"detail": "Upload exceeds 15 MiB"}, status_code=413)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


latest_alert = None
alert_lock = asyncio.Lock()
frame_lock = asyncio.Lock()


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(Path(__file__).parent / "dashboard" / "index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/live")
async def live_status():
    return JSONResponse(app.state.watcher.status(), headers={"Cache-Control": "no-store"})


@app.get("/latest")
async def get_latest():
    async with alert_lock:
        try:
            expired = latest_alert is None or not 0 <= time.time() - timestamp(latest_alert["timestamp"]) <= 30
        except (ValueError, TypeError, KeyError):
            expired = True
        if expired:
            return Response(status_code=204)
        alert = latest_alert
    if os.getenv("FIRESIGHT_DEMO_MAP") == "true":
        # Placeholder map for demos; the glasses re-download it only when map_url changes.
        alert = {**alert, "map_url": f"/view.png?v={alert['id']}"}
    return JSONResponse(content=alert)


@app.get("/view.png")
async def get_view(v: str = ""):
    """Placeholder tactical map; the fire's size and position are seeded by v."""
    if os.getenv("FIRESIGHT_DEMO_MAP") != "true":
        return Response(status_code=404)
    return Response(content=await asyncio.to_thread(render_map, v), media_type="image/png")


class G2DisplayReport(BaseModel):
    alert_id: str = Field(min_length=1, max_length=128)
    rendered_text: str = Field(max_length=2048)
    status: str = Field(pattern="^(sdk_accepted|failed|cleared)$")


g2_report = None


@app.post("/g2/display")
async def report_g2_display(payload: G2DisplayReport, request: Request):
    global g2_report
    token = os.getenv("G2_REPORT_TOKEN", "")
    if not token:
        raise HTTPException(503, "G2 display reporting is not configured")
    if not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
        raise HTTPException(401, "Invalid display-report token")
    g2_report = {**payload.model_dump(), "received_at": datetime.now(timezone.utc).isoformat()}
    return {"ok": True}


@app.get("/g2/status")
async def g2_status():
    report = g2_report
    fresh = bool(report and time.time() - timestamp(report["received_at"]) <= 15)
    return JSONResponse({"reporting_configured": bool(os.getenv("G2_REPORT_TOKEN")),
                         "fresh": fresh, "report": report}, headers={"Cache-Control": "no-store"})


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


@app.post("/frame")
async def upload_frame(request: Request):
    """Analyze one JPEG/PNG frame; the drone client calls this once per second."""
    global latest_alert
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type == "multipart/form-data":
        try:
            form = await request.form()
        except Exception as error:
            raise HTTPException(status_code=400, detail="Could not read multipart frame upload") from error
        upload = form.get("frame") or form.get("image")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(status_code=422, detail="Multipart upload must include a 'frame' file")
        image_bytes = await upload.read()
        image_type = (getattr(upload, "content_type", None) or "").split(";", 1)[0].strip().lower()
        if image_type not in SUPPORTED_IMAGE_TYPES:
            filename = (getattr(upload, "filename", "") or "").lower()
            if filename.endswith(".png"):
                image_type = "image/png"
            elif filename.endswith((".jpg", ".jpeg")):
                image_type = "image/jpeg"
    else:
        image_type = content_type
        image_bytes = await request.body()

    if image_type == "image/jpg":
        image_type = "image/jpeg"
    if image_type not in SUPPORTED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Content-Type must be image/jpeg or image/png")
    try:
        # Preserve frame order when analysis takes longer than the send interval.
        async with frame_lock:
            alert = await asyncio.to_thread(analyze_frame, image_bytes, image_type)
            async with alert_lock:
                latest_alert = alert
    except GeminiConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except GeminiRequestError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except (ValueError, cv2.error) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return JSONResponse(content=alert)
