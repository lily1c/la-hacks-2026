# FireSight

FireSight receives paired drone JPEGs and telemetry from Beagle Eyes, analyzes frames, and serves a map dashboard and alerts to an Even Realities G2 phone app.

```text
Greg's computer: drone → Beagle Eyes → HTTPS image + telemetry
                                           ↓
Render: receiver → latest-frame analysis → alert JSON
           ↓                                  ↓
       dashboard                 Even Hub phone app → G2
           ↑                                  ↓
           └──────── SDK display report ──────┘
```

## Run locally

Python 3.10+ is required. From the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
export INGEST_MODE=push
export FIRESIGHT_DETECTOR=opencv
export INGEST_TOKEN=replace-with-a-private-token
export G2_REPORT_TOKEN=replace-with-a-separate-private-token
uvicorn firesight.api:app --host 127.0.0.1 --port 8790
```

Open http://127.0.0.1:8790. No incoming frames is a normal waiting state. Greg uses the hosted HTTPS endpoint, not your localhost.

## Project structure

| Directory | Responsibility |
| --- | --- |
| `src/firesight/api.py` | HTTP entry point; stable routes |
| `src/firesight/ingestion/` | Push receiver and optional legacy bundle readers |
| `src/firesight/analysis/` | Image/video processing, OpenCV and Gemini |
| `src/firesight/contracts/` | Shared alert validation |
| `src/firesight/services/` | Optional demo image rendering |
| `src/firesight/dashboard/` | HTML, CSS and JavaScript served by the API |
| `glasses-app/` | Even Hub TypeScript client |
| `integrations/beagle_push/` | Sender installed on Greg's computer |
| `demos/` | Synthetic inputs, separate from live ingestion |
| `deploy/` | Docker deployment |
| `tests/` | Receiver and API regression tests |
| `docs/` | Architecture, contracts, setup and verification |

Old Python module imports remain supported by compatibility modules. Greg's GPU software stays in his separate repository. The old VM deployment remains available in `vm-setup`; it is not required for this push deployment.

## Dashboard & Beagle Eyes Integration

The map-first FireSight dashboard (`src/firesight/dashboard/index.html`) integrates directly with **Beagle Eyes** (`vendor/beagle_eyes`) for both:
- **Live 30 FPS video & telemetry streaming** over WebSocket (`ws://<beagle-host>:8765/ws`), displaying real-time DPVO XYZ pose, stream FPS / VO Hz, inference latency, 3D person detections, and live map trajectory.
- **FireSight AI hazard analysis & G2 glasses alerts**, where `TelemetryBroadcaster` (`vendor/beagle_eyes/broadcast/broadcaster.py`) serves paired `firesight.frame.v1` frame + telemetry bundles on `GET /snapshot` (port `8765`) and optionally pushes bundles to `POST /ingest/beagle` when `FIRESIGHT_URL` is set.

### 1. Install Beagle Eyes (`vendor/beagle_eyes`)

Run the installer script to clone/update `vendor/beagle_eyes`, initialize the `Deep-Visual-Odometry-SLAM` submodule cleanly, and build DPVO CUDA extensions if a CUDA toolkit is present:

```sh
./scripts/install_beagle_eyes.sh
# Or skip CUDA extension compilation (e.g., when only running mock_sender.py):
./scripts/install_beagle_eyes.sh vendor/beagle_eyes --skip-build
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

## Setup and verification

- [Greg's sender](integrations/beagle_push/README.md)
- [Glasses setup](docs/glasses-setup.md)
- [Architecture and branch decisions](docs/architecture.md)
- [API contracts](docs/api-contracts.md)
- [Testing](docs/testing.md)
- [Demo instructions](docs/demos.md)

Render uses `render.yaml`, targeting `main`. An existing manually configured Render service may still require its branch setting to be changed in the dashboard. Keep existing tokens unchanged when deploying.

OpenCV is a color heuristic. Gemini is optional and requires an API key and a model available to your account via `GEMINI_MODEL`. This project does not currently implement Llama or ElevenLabs. Telemetry is relative odometry, not GPS. Generated demo maps are not geographic navigation. Phone GPS and voice-report backend support remain separate work.
