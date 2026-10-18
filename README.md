# FireSight

FireSight accepts one JPEG or PNG frame per request. The drone pipeline can send a new frame once per second; when a Gemini API key is configured, each frame is analyzed by a Gemini vision language model and a compact alert is published for the glasses app. The local OpenCV detector remains available as a fallback. A batch video endpoint remains available for local clips and uses OpenCV.

## Project layout

```text
src/firesight/
  alerts.py      alert contract and validation
  api.py         upload and latest-alert HTTP routes
  cli.py         command-line entry point
  frame.py       JPEG/PNG decoding and single-frame analysis
  gemini.py      Gemini multimodal image detection
  detector.py    Gemini/OpenCV detector selection
  video.py       OpenCV video sampling and JPEG extraction
  vision.py      frame detection and grid ranking
mock_server.js   lightweight glasses API mock
```

## Install and run the API

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
uvicorn firesight.api:app --host 0.0.0.0 --port 8787
```

To use Gemini vision for single-frame detection, create an API key in [Google AI Studio](https://aistudio.google.com/app/apikey) and set these variables in the same terminal before starting the API or CLI:

```sh
export GEMINI_API_KEY='your-google-ai-studio-api-key'
export FIRESIGHT_DETECTOR=gemini
# Optional; defaults to gemini-3.8-flash
export GEMINI_MODEL=gemini-3.8-flash
```

`FIRESIGHT_DETECTOR=auto` (the default) uses Gemini when `GEMINI_API_KEY` is set, otherwise it uses local OpenCV. Set it to `opencv` to force local detection. Gemini analyzes each submitted frame and usage may incur API charges. The API key is read from the process environment and is never written to alert output or a project file.

The API allows cross-origin requests and exposes:

- `GET /latest` — `204 No Content` before an alert exists; otherwise `200 OK` with `Content-Type: application/json`.
- `POST /frame` — analyze one JPEG or PNG picture using the selected detector, publish its alert, and return it. Send one request for each frame, once per second.
- `POST /video` — upload a video as multipart field `video`; it analyzes frames, publishes the alert, and returns it.
- `POST /latest` — publish a prepared alert, useful for connecting an upstream LLM or exercising the glasses UI.
- `GET /health` — simple readiness check.

Send frame bytes directly with the matching image content type:

```sh
curl -X POST http://localhost:8787/frame \
  -H 'Content-Type: image/jpeg' \
  --data-binary '@path/to/frame.jpg'

curl -i http://localhost:8787/latest
```

For PNG, send `Content-Type: image/png` and the `.png` path. Multipart uploads also work using a `frame` file field. Each frame request replaces the latest alert in arrival order. The `/video` batch route samples one frame per second by default and returns an alert based on the strongest sampled OpenCV fire signal.

## Glasses alert contract

Responses use this shape:

```json
{
  "id": "1792277038391",
  "timestamp": "2026-10-17T22:42:10Z",
  "priority": "critical",
  "headline": "Fire detected - use caution",
  "instructions": [
    "Check upper-right frame sector",
    "Check center frame sector"
  ]
}
```

The headline and each instruction are limited to 40 characters. There can be up to five instructions. Priorities are `critical`, `warning`, or `info`; unknown priorities submitted to `POST /latest` become `info`. CORS allows all origins for the glasses app.

Image analysis cannot infer safe paths, real-world distances, crew locations, or compass directions from a single frame. The Gemini prompt restricts instructions to visible evidence and relative image positions; alerts are not evacuation guidance. Add trusted GPS, wind, terrain, and crew data before generating operational routing instructions.

## Test the glasses API without video processing

The Node mock implements `GET /latest` and `POST /latest` on port 8787:

```sh
npm run mock
```

In another terminal, publish a test alert:

```sh
curl -i -X POST http://localhost:8787/latest \
  -H 'Content-Type: application/json' \
  -d '{"priority":"critical","headline":"Test alert","instructions":["Check upper-right sector","Move 20m south"]}'

curl -i http://localhost:8787/latest
```

## Run the analyzer directly

The installed CLI accepts either a JPEG/PNG picture or a video and writes the alert JSON beside the input:

```sh
firesight-analyze path/to/frame.jpg --out alert.json
firesight-analyze path/to/drone_video.mp4 --sample-seconds 0.5 --out alert.json
```

The root-level `wildfire_analyzer.py` remains as a compatibility launcher for existing commands.

JPEG/PNG analysis uses Gemini Vision when configured, or a single-frame OpenCV color/brightness heuristic. Video analysis uses OpenCV. Neither detector is a verified fire assessment; video/container support depends on the codecs available in the local OpenCV build.

## Dashboard & Beagle Eyes Integration

The map-first FireSight dashboard (`src/firesight/dashboard/index.html`) integrates directly with **Beagle Eyes** (`vendor/beagle_eyes`) for both:
- **Live 30 FPS video & telemetry streaming** over WebSocket (`ws://<beagle-host>:8765/ws`), displaying real-time DPVO XYZ pose, stream FPS / VO Hz, inference latency, 3D person detections, and live map trajectory.
- **FireSight AI hazard analysis & G2 glasses alerts**, where `TelemetryBroadcaster` (`vendor/beagle_eyes/broadcast/broadcaster.py`) serves paired `firesight.frame.v1` frame + telemetry bundles on `GET /snapshot` (port `8765`) and optionally pushes bundles to `POST /ingest/beagle` when `FIRESIGHT_URL` is set.

### 1. Install Beagle Eyes (`vendor/beagle_eyes`)

Run the installer script to clone/update `vendor/beagle_eyes`, initialize the `Deep-Visual-Odometry-SLAM` submodule cleanly, and build DPVO CUDA extensions if a CUDA toolkit is present:

```sh
./packages/install_beagle_eyes.sh
# Or skip CUDA extension compilation (e.g., when only running mock_sender.py):
./packages/install_beagle_eyes.sh vendor/beagle_eyes --skip-build
```

### 2. Run Beagle Eyes + FireSight Dashboard (Local End-to-End)

#### Terminal 1 — Start Beagle Eyes Broadcaster (Port `8765`)

Activate your environment (`conda activate visual_slam` for DPVO) and start one of the Beagle Eyes sources:

```sh
# Option A: Mock 3D flight + telemetry (instant test, no drone or GPU needed)
python3 vendor/beagle_eyes/broadcast/mock_sender.py
# (Add --webcam to stream real /dev/video0 webcam video with mock 3D telemetry)

# Option B: Laptop webcam + live DPVO + 3D Person Survey
python3 vendor/beagle_eyes/scripts/webcam_vo.py --detect-people

# Option C: DJI Mini 5 Pro (RC 2) RTMP stream + live DPVO + 3D Person Survey
python3 vendor/beagle_eyes/scripts/uav_vo.py \
  --config vendor/beagle_eyes/config/uav_config.yaml \
  --plot-mode 3d --stride 2 --vo-scale 0.5 --detect-people
```

When running, `TelemetryBroadcaster` serves on port `8765`:
- `ws://<ip>:8765/ws` — Live 30 FPS binary JPEG frames + 30 Hz JSON telemetry
- `http://<ip>:8765/video.mjpg` — Live MJPEG video stream
- `http://<ip>:8765/snapshot` — Paired `firesight.frame.v1` JSON bundle (`jpeg_base64`, `sha256`, `telemetry`, `metadata`)
- `http://<ip>:8765/status` — Broadcaster health and client count

#### Terminal 2 — Start FireSight API & Dashboard (Port `8787`)

```sh
PYTHONPATH=src uvicorn firesight.api:app --host 0.0.0.0 --port 8787
```

Open **http://127.0.0.1:8787/** in your browser:
- By default, the FireSight backend automatically polls `http://127.0.0.1:8765/snapshot`, runs the configured fire/hazard detector (`opencv` or `gemini`), updates `/live` and `/latest` for the G2 glasses app, and forwards matched metadata.
- Meanwhile, the browser dashboard connects directly to `ws://127.0.0.1:8765/ws` for zero-lag 30 FPS video, live XYZ coordinates, FPS / VO Hz, 3D person detections, and live drone path rendering on the 3D map.

### 3. Cross-Laptop / Remote Connection Options

If Beagle Eyes (Laptop A) and the FireSight dashboard/backend (Laptop B or Render) are on separate machines:

- **Same LAN / Cloudflare Tunnel (Browser WS + Backend Poll)**:
  - Point the dashboard's **System links** host input (or URL query param `?beagle=<laptop-A-ip>:8765` or `https://xxxx.trycloudflare.com`) to Laptop A.
  - On the FireSight backend, set `BEAGLE_URL='http://<laptop-A-ip>:8765/snapshot'` (and optional shared `BEAGLE_EXPORT_TOKEN`).
- **Outbound Push from Beagle Eyes to Hosted FireSight (`INGEST_MODE=push`)**:
  - On the hosted FireSight backend, set `INGEST_MODE=push` and `INGEST_TOKEN='<shared-secret>'`.
  - On Laptop A running Beagle Eyes, set `FIRESIGHT_URL='https://your-firesight-host.onrender.com'` and `INGEST_TOKEN='<shared-secret>'` before launching `uav_vo.py`, `webcam_vo.py`, or `mock_sender.py`. `TelemetryBroadcaster` will automatically push paired frames and telemetry to `/ingest/beagle` in the background.

## G2 display monitor and API

The dedicated G2 panel polls the same GET /latest endpoint used by the glasses app, independently of manual/drone preview. The left side shows the outgoing alert formatted approximately like the G2 text layout (9 lines, 44 characters). It is not a hardware screenshot; maps, microphone status, local time zone and transient phone messages may differ.

The right side shows the exact rendered_text supplied by the phone app, with alert ID and server receipt time. Until the phone integrates the report call, it correctly says display unconfirmed. Reports expire as connection evidence after 15 seconds. The SDK accepting an update is not proof the wearer saw it.

Configure G2_REPORT_TOKEN on the backend, then add a report call to the glasses-app branch after checking the actual success result of createStartUpPageContainer, rebuildPageContainer or textContainerUpgrade. Do not mark text as shown before that operation succeeds. Send the rendered container text, not a fresh rendering of an alert that may have changed while awaiting Bluetooth:

```typescript
await fetch(new URL('/g2/display', SUMMARY_URL), {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${import.meta.env.VITE_G2_REPORT_TOKEN}`,
  },
  body: JSON.stringify({
    alert_id: displayedAlertId,
    rendered_text: displayedContainerText,
    status: 'sdk_accepted', // alternatively failed or cleared
  }),
})
```

The variable names in this snippet refer to the captured alert ID and text of the SDK update; they must be wired into the phone's refresh function. Send a heartbeat report every five seconds while the bridge is known to be active; do not report success merely because /latest was fetched. Report failed on an SDK failure, and cleared when clearing expired content. Handle reporting errors without interrupting display updates. The glasses-app/ copy in this dashboard branch now sends these reports after checking SDK results. The separate upstream glasses-app branch is unchanged.

GET /g2/status is read by the dashboard and returns reporting_configured, fresh and report. POST /g2/display requires the separate shared token (503 when unset, 401 when incorrect), a nonempty alert_id up to 128 characters, rendered_text up to 2048 characters, and status sdk_accepted/failed/cleared. It retains the last report in memory for this single-device prototype. Restarting clears it. Use HTTPS for remote connections and never use the model API key as the report token. Configure VITE_SUMMARY_URL and the Even Hub network whitelist to the same reachable backend origin. A phone’s localhost does not refer to this computer.

## Render deployment

Use the root render.yaml Blueprint on branch feature/dashboard. It deploys the Docker backend and dashboard together, binds Render's PORT and runs one worker (latest alerts and phone reports are process-local). Free hosting can sleep after inactivity; restarts clear current state. This is a hackathon deployment, not durable incident storage.

The Blueprint defaults to OpenCV and generates separate INGEST_TOKEN and G2_REPORT_TOKEN values. Copy G2_REPORT_TOKEN privately from Render into the phone app's VITE_G2_REPORT_TOKEN and rebuild using the actual Render URL. Never commit either token. Enter INGEST_TOKEN in the dashboard upload field to analyze manual frames; POST /frame, /video and /latest require it in hosted mode. The token is kept only in the input, not browser storage. Uploads are limited to 15 MiB in hosted mode.

The dashboard and read endpoints are public in this prototype. Only use demo imagery suitable for the project's public dashboard. Private incident deployment requires read authentication too.

Leave BEAGLE_URL unset until Greg provides a reachable endpoint. Render cannot connect directly to 172.20.10.2 or another laptop's private LAN IP. Greg must provide an HTTPS tunnel/private network connection to his authenticated snapshot exporter; then configure BEAGLE_URL and BEAGLE_EXPORT_TOKEN in Render. Do not expose the export token in URLs. No GPU is required for the default OpenCV backend. Configuring Gemini requires a separate server-side API key and provider-supported model.
