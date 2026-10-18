"""HTTP API: upload drone videos and expose the latest glasses alert."""
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hmac
import json
import os
import sys
from pathlib import Path
import re
import tempfile
import time

import cv2

from firesight.config import load_dotenv
from firesight.alerts import validate_alert
from firesight.mapview import render_map
from firesight.frame import SUPPORTED_IMAGE_TYPES, analyze_frame
from firesight.gemini import GeminiConfigurationError, GeminiRequestError
from firesight.live import BundleWatcher, RemoteBeagleWatcher, timestamp
from firesight.push import PushReceiver
from firesight.services.annotations import AnnotationService
from firesight.video import analyze_video

try:
    from fastapi import FastAPI, File, HTTPException, Request, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles
    _HAS_FASTAPI = True
except ModuleNotFoundError:
    _HAS_FASTAPI = False


if not {"unittest", "pytest"} & set(sys.modules):  # tests must not pick up a real API key
    load_dotenv()
latest_alert = None
g2_report = None
alert_lock = asyncio.Lock()
frame_lock = asyncio.Lock()

_G2_STATUS_RE = re.compile(r"^(sdk_accepted|failed|cleared)$")


def _validate_g2_report(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")
    alert_id = data.get("alert_id")
    rendered_text = data.get("rendered_text")
    status = data.get("status")
    if not isinstance(alert_id, str) or not (1 <= len(alert_id) <= 128):
        raise ValueError("alert_id must be a string between 1 and 128 chars")
    if not isinstance(rendered_text, str) or len(rendered_text) > 2048:
        raise ValueError("rendered_text must be a string up to 2048 chars")
    if not isinstance(status, str) or not _G2_STATUS_RE.match(status):
        raise ValueError("status must be sdk_accepted, failed, or cleared")
    return {"alert_id": alert_id, "rendered_text": rendered_text, "status": status}


async def publish_live(alert):
    global latest_alert
    async with alert_lock:
        latest_alert = alert


def _create_watcher():
    if os.getenv("INGEST_MODE") == "push":
        return PushReceiver(analyze_frame, publish_live, frame_lock)
    if os.getenv("FRAME_DIR"):
        return BundleWatcher(os.getenv("FRAME_DIR"), analyze_frame, publish_live, frame_lock)
    if os.getenv("BEAGLE_URL"):
        return RemoteBeagleWatcher(
            os.environ["BEAGLE_URL"], os.getenv("BEAGLE_EXPORT_TOKEN", ""), analyze_frame, publish_live, frame_lock
        )
    if os.getenv("PUBLIC_DEPLOYMENT") == "true":
        return PushReceiver(analyze_frame, publish_live, frame_lock)
    return RemoteBeagleWatcher(
        "http://127.0.0.1:8765/snapshot",
        os.getenv("BEAGLE_EXPORT_TOKEN", ""),
        analyze_frame,
        publish_live,
        frame_lock,
    )


def _fetch_fresh_frame():
    """Newest Beagle frame straight from the broadcaster, bypassing the watcher's (possibly busy) analysis loop."""
    watcher = app.state.watcher
    data = watcher.fetch() if hasattr(watcher, "fetch") else None
    if not data:
        return None
    metadata = data["metadata"]
    return {"frame_id": metadata["frame_id"], "metadata": metadata, "image": "data:image/jpeg;base64," + data["jpeg_base64"]}


if _HAS_FASTAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.watcher = _create_watcher()
        app.state.annotations = AnnotationService(
            lambda: getattr(app.state.watcher, "snapshot", None), fetch_fresh=_fetch_fresh_frame)
        tasks = [asyncio.create_task(app.state.watcher.run()), asyncio.create_task(app.state.annotations.run())]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="FireSight API", version="1.0.0", lifespan=lifespan)
    app.mount("/assets", StaticFiles(directory=Path(__file__).parent / "dashboard"), name="assets")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def protect_public_writes(request: Request, call_next):
        if os.getenv("PUBLIC_DEPLOYMENT") == "true" and request.method == "POST" and request.url.path in ("/frame", "/video", "/latest", "/ingest/beagle", "/annotations/config", "/annotations/run"):
            token = os.getenv("INGEST_TOKEN", "")
            if not token or not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
                return JSONResponse({"detail": "A valid ingest token is required"}, status_code=401)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 15 * 1024 * 1024:
                    return JSONResponse({"detail": "Upload exceeds 15 MiB"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/", include_in_schema=False)
    async def dashboard():
        return FileResponse(Path(__file__).parent / "dashboard" / "index.html")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/live")
    async def live_status():
        return JSONResponse(app.state.watcher.status(), headers={"Cache-Control": "no-store"})

    @app.get("/annotations")
    async def get_annotations():
        return JSONResponse(app.state.annotations.state(), headers={"Cache-Control": "no-store"})

    @app.post("/annotations/config")
    async def configure_annotations(payload: dict):
        try:
            return JSONResponse(app.state.annotations.configure(
                payload.get("prompt"), payload.get("auto"), payload.get("interval_s")))
        except (TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post("/annotations/run")
    async def run_annotations():
        return JSONResponse(await app.state.annotations.run_once())

    @app.delete("/annotations")
    async def clear_annotations():
        return JSONResponse(app.state.annotations.clear())

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
            # Gemini reports fire_sector; the OpenCV detector names it in "Check <sector> frame sector".
            sector = alert.get("fire_sector")
            if not sector:
                matches = (re.match(r"Check (.+) frame sector", line) for line in alert["instructions"])
                match = next((m for m in matches if m), None)
                sector = match.group(1) if match else "none"
            alert = {**alert, "map_url": f"/view.png?v={alert['id']}&dir={sector}"}
        return JSONResponse(content=alert)

    @app.get("/view.png")
    async def get_view(v: str = "", dir: str = ""):
        """Placeholder tactical map; fire placed in the reported sector, details seeded by v."""
        if os.getenv("FIRESIGHT_DEMO_MAP") != "true":
            return Response(status_code=404)
        return Response(content=await asyncio.to_thread(render_map, v, dir or None), media_type="image/png")

    @app.post("/g2/display")
    async def report_g2_display(payload: dict, request: Request):
        global g2_report
        token = os.getenv("G2_REPORT_TOKEN", "")
        if not token:
            raise HTTPException(503, "G2 display reporting is not configured")
        if not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
            raise HTTPException(401, "Invalid display-report token")
        try:
            validated = _validate_g2_report(payload)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        g2_report = {**validated, "received_at": datetime.now(timezone.utc).isoformat()}
        return {"ok": True}

    @app.get("/g2/status")
    async def g2_status():
        report = g2_report
        fresh = bool(report and time.time() - timestamp(report["received_at"]) <= 15)
        return JSONResponse(
            {"reporting_configured": bool(os.getenv("G2_REPORT_TOKEN")), "fresh": fresh, "report": report},
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/latest")
    async def publish_latest(payload: dict):
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

    @app.post("/ingest/beagle")
    async def ingest_beagle(request: Request):
        token = os.getenv("INGEST_TOKEN", "")
        if token or os.getenv("PUBLIC_DEPLOYMENT") == "true":
            if not token or not hmac.compare_digest(request.headers.get("Authorization", ""), "Bearer " + token):
                raise HTTPException(401, "Invalid ingest token")
        if not hasattr(app.state.watcher, "accept"):
            raise HTTPException(503, "Set INGEST_MODE=push to enable Beagle ingestion")
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 12 * 1024 * 1024:
                raise HTTPException(413, "Bundle exceeds 12 MiB")
        try:
            result = app.state.watcher.accept(json.loads(body))
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise HTTPException(422, "Invalid frame bundle: " + str(error)) from error
        return JSONResponse(result, status_code=202 if result["accepted"] else 200)

else:
    class _MinimalASGIApp:
        """Zero-dependency ASGI app so `uvicorn firesight.api:app` runs even without FastAPI installed."""

        def __init__(self):
            self.watcher = None
            self._task = None

        async def _send_response(self, send, status: int, body: bytes, content_type: str = "application/json"):
            headers = [
                (b"content-type", content_type.encode("latin-1")),
                (b"content-length", str(len(body)).encode("latin-1")),
                (b"cache-control", b"no-store"),
                (b"access-control-allow-origin", b"*"),
                (b"access-control-allow-methods", b"GET, POST, OPTIONS"),
                (b"access-control-allow-headers", b"*"),
            ]
            await send({"type": "http.response.start", "status": status, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        async def _send_json(self, send, data, status: int = 200):
            await self._send_response(send, status, json.dumps(data).encode("utf-8"), "application/json")

        async def _read_body(self, receive, max_bytes: int = 15 * 1024 * 1024) -> bytes:
            buf = bytearray()
            while True:
                msg = await receive()
                chunk = msg.get("body", b"")
                if chunk:
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise BufferError("Payload too large")
                if not msg.get("more_body", False):
                    break
            return bytes(buf)

        async def __call__(self, scope, receive, send):
            global latest_alert, g2_report
            scope_type = scope["type"]
            if scope_type == "lifespan":
                while True:
                    msg = await receive()
                    if msg["type"] == "lifespan.startup":
                        self.watcher = _create_watcher()
                        self._task = asyncio.create_task(self.watcher.run())
                        await send({"type": "lifespan.startup.complete"})
                    elif msg["type"] == "lifespan.shutdown":
                        if self._task:
                            self._task.cancel()
                            with suppress(asyncio.CancelledError):
                                await self._task
                        await send({"type": "lifespan.shutdown.complete"})
                        return
                return

            if scope_type != "http":
                return

            if self.watcher is None:
                self.watcher = _create_watcher()
                self._task = asyncio.create_task(self.watcher.run())

            method = scope["method"].upper()
            path = scope["path"]
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}

            if method == "OPTIONS":
                await self._send_response(send, 204, b"", "text/plain")
                return

            if os.getenv("PUBLIC_DEPLOYMENT") == "true" and method == "POST" and path in ("/frame", "/video", "/latest", "/ingest/beagle"):
                token = os.getenv("INGEST_TOKEN", "")
                if not token or not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + token):
                    await self._send_json(send, {"detail": "A valid ingest token is required"}, 401)
                    return

            if method == "GET" and path == "/":
                html_bytes = (Path(__file__).parent / "dashboard" / "index.html").read_bytes()
                await self._send_response(send, 200, html_bytes, "text/html; charset=utf-8")
                return

            if method == "GET" and path.startswith("/assets/"):
                assets_dir = (Path(__file__).parent / "dashboard").resolve()
                asset = (assets_dir / path[len("/assets/"):]).resolve()
                if asset.parent != assets_dir or not asset.is_file():
                    await self._send_json(send, {"detail": "Not found"}, 404)
                    return
                kind = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".mp4": "video/mp4"}.get(asset.suffix, "application/octet-stream")
                await self._send_response(send, 200, asset.read_bytes(), kind)
                return

            if method == "GET" and path == "/health":
                await self._send_json(send, {"status": "ok"})
                return

            if method == "GET" and path == "/live":
                await self._send_json(send, self.watcher.status())
                return

            if method == "GET" and path == "/latest":
                async with alert_lock:
                    try:
                        expired = latest_alert is None or not 0 <= time.time() - timestamp(latest_alert["timestamp"]) <= 30
                    except (ValueError, TypeError, KeyError):
                        expired = True
                    if expired:
                        await self._send_response(send, 204, b"", "text/plain")
                    else:
                        await self._send_json(send, latest_alert)
                return

            if method == "GET" and path == "/g2/status":
                report = g2_report
                fresh = bool(report and time.time() - timestamp(report["received_at"]) <= 15)
                await self._send_json(
                    send,
                    {"reporting_configured": bool(os.getenv("G2_REPORT_TOKEN")), "fresh": fresh, "report": report},
                )
                return

            if method == "POST" and path == "/g2/display":
                token = os.getenv("G2_REPORT_TOKEN", "")
                if not token:
                    await self._send_json(send, {"detail": "G2 display reporting is not configured"}, 503)
                    return
                if not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + token):
                    await self._send_json(send, {"detail": "Invalid display-report token"}, 401)
                    return
                try:
                    raw = await self._read_body(receive, 65536)
                    validated = _validate_g2_report(json.loads(raw))
                except Exception as error:
                    await self._send_json(send, {"detail": str(error)}, 422)
                    return
                g2_report = {**validated, "received_at": datetime.now(timezone.utc).isoformat()}
                await self._send_json(send, {"ok": True})
                return

            if method == "POST" and path == "/latest":
                try:
                    raw = await self._read_body(receive, 1024 * 1024)
                    alert = validate_alert(json.loads(raw))
                except Exception as error:
                    await self._send_json(send, {"detail": str(error)}, 422)
                    return
                async with alert_lock:
                    latest_alert = alert
                await self._send_json(send, alert)
                return

            if method == "POST" and path == "/frame":
                content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type == "image/jpg":
                    content_type = "image/jpeg"
                if content_type not in SUPPORTED_IMAGE_TYPES:
                    await self._send_json(send, {"detail": "Content-Type must be image/jpeg or image/png"}, 415)
                    return
                try:
                    image_bytes = await self._read_body(receive, 15 * 1024 * 1024)
                    async with frame_lock:
                        alert = await asyncio.to_thread(analyze_frame, image_bytes, content_type)
                        async with alert_lock:
                            latest_alert = alert
                except BufferError:
                    await self._send_json(send, {"detail": "Upload exceeds 15 MiB"}, 413)
                    return
                except GeminiConfigurationError as error:
                    await self._send_json(send, {"detail": str(error)}, 503)
                    return
                except GeminiRequestError as error:
                    await self._send_json(send, {"detail": str(error)}, 502)
                    return
                except (ValueError, cv2.error) as error:
                    await self._send_json(send, {"detail": str(error)}, 400)
                    return
                await self._send_json(send, alert)
                return

            if method == "POST" and path == "/ingest/beagle":
                token = os.getenv("INGEST_TOKEN", "")
                if token or os.getenv("PUBLIC_DEPLOYMENT") == "true":
                    if not token or not hmac.compare_digest(headers.get("authorization", ""), "Bearer " + token):
                        await self._send_json(send, {"detail": "Invalid ingest token"}, 401)
                        return
                if not hasattr(self.watcher, "accept"):
                    await self._send_json(send, {"detail": "Set INGEST_MODE=push to enable Beagle ingestion"}, 503)
                    return
                try:
                    body = await self._read_body(receive, 12 * 1024 * 1024)
                    result = self.watcher.accept(json.loads(body))
                except BufferError:
                    await self._send_json(send, {"detail": "Bundle exceeds 12 MiB"}, 413)
                    return
                except (ValueError, KeyError, TypeError, AttributeError) as error:
                    await self._send_json(send, {"detail": "Invalid frame bundle: " + str(error)}, 422)
                    return
                await self._send_json(send, result, 202 if result["accepted"] else 200)
                return

            await self._send_json(send, {"detail": "Not Found"}, 404)

    app = _MinimalASGIApp()
