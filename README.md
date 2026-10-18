# FireSight

FireSight receives paired drone JPEGs and telemetry from Beagle Eyes, analyzes frames, and serves a map dashboard and alerts to an Even Realities G2 phone app. The glasses report the wearer's GPS and sensor telemetry back, so command sees each firefighter on the map and the glasses show distance and direction to mapped fires.

```text
Greg's computer: drone → Beagle Eyes → HTTPS image + telemetry
                                           ↓
Render: receiver → analysis + Gemini map annotations → alert JSON
           ↓                                              ↓
       dashboard                        Even Hub phone app → G2
           ↑                                              ↓
           ├──────────── SDK display report ──────────────┤
           └──── wearer GPS, IMU, buttons, SOS/man-down ──┘
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
| `src/firesight/services/` | Gemini annotations and geo projection, wearer GPS/telemetry (`wearer.py`), glasses maps (`wearer_map.py`, demo `mapview.py`), opt-in demo fire |
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

## Gemini map annotations

Tell Gemini what to mark; it returns regions in the drone frame, which are cast onto the ground and drawn on the map. Use the **Gemini annotations** card in the dashboard: type an instruction (or pick a preset such as *Car crash* or *Trees*), press **Annotate now** or turn on **Auto**, and toggle layers per kind.

**API key.** Create a key in [Google AI Studio](https://aistudio.google.com/apikey) and put it in a git-ignored `.env` at the repository root (the server loads it at startup; real environment variables win):

```sh
cp .env.example .env     # then edit GEMINI_API_KEY=...
```

Never commit `.env`, and never put the key in the dashboard or glasses app. Optional settings: `GEMINI_ANNOTATE_MODEL` (fast model for annotations, default `gemini-3.5-flash-lite`; use a model your key can access) and `GEMINI_MODEL` (frame analysis).

**Placement needs geo telemetry.** Start Beagle Eyes with `--gps-tf` (see `vendor/beagle_eyes/gps_tf/README.md`):

```sh
python scripts/uav_vo.py --detect-people --gps-tf --gps-origin 34.070233,-118.445185 \
  --gps-heading 0 --gps-cam-pitch 0 --gps-start-height 1.5 --gps-autocal
```

Without it, Gemini still runs but annotations are listed as "not placed". Results are approximate until scale is calibrated.

API: `GET /annotations`, `POST /annotations/config` (`prompt`, `auto`, `interval_s`), `POST /annotations/run`, `DELETE /annotations`.
Latency: frames are downscaled to 768 px, thinking is minimal, and calls run off the video path. Annotations expire after 60 s.

## G2 glasses: what works

The glasses app is in [`glasses-app/`](glasses-app/README.md). **To install and run it on G2 (or the simulator), including the accounts, keys and tokens a tester needs, see [Install and run on G2](glasses-app/README.md#install-and-run-on-g2).** Tested on real G2 glasses:

- **Alerts:** the latest drone-frame alert (priority, headline, instructions), refreshed every 2 s. Alerts older than 15 s are cleared; `NO SIGNAL` shows when the backend is unreachable.
- **Wearer GPS:** the phone's GPS goes to `POST /wearer` every 5 s. The reply lists the nearest mapped hazards (Gemini annotations placed by `gps_tf`), and the glasses show e.g. `>> Fire front: ~180 m NE`.
- **GPS-built alert and map:** with no drone alert active, the glasses show an alert built from GPS (distance, direction, "Closing in" / "Moving away") and a north-up map around the wearer with hazards at their true offset and a zooming scale bar. It updates as the wearer moves.
- **Telemetry:** IMU (accelerometer, 10 Hz), button presses with their source (right/left temple, R1 ring) and battery/charging. The backend derives a motion state: still, walking or tilted.
- **Safety:** an impact above 3 g followed by stillness asks "Are you OK?"; no tap within 20 s reports **MAN DOWN**. Holding a temple sends **SOS**. Both turn the wearer red on the dashboard map with a banner.
- **Controls:** tap = I'm OK / cancel SOS / acknowledge the alert; hold = SOS; scroll = step through nearby hazards; double-tap = exit.
- **Dashboard:** each wearer is a marker on the map with motion and battery, and the G2 card shows what the glasses reported displaying (or a recorded demo when no phone is reporting).

Limits: directions are compass directions from GPS (about ±3° at 160 m, unreliable under ~25 m). The glasses can't sense which way the head is turned (no magnetometer), and their "worn" flag does not change when the glasses are taken off.

To try the GPS features without a drone, set `FIRESIGHT_DEMO_HAZARD=true` on the backend: a "Demo fire" is placed 180 m north-east of the first wearer (`FIRESIGHT_DEMO_HAZARD_M` to change the distance) and stays put, so walking changes the distance. Real annotations replace it.

## G2 display monitor and API

The dedicated G2 panel polls the same GET /latest endpoint used by the glasses app, independently of manual/drone preview. The left side shows the outgoing alert formatted approximately like the G2 text layout (9 lines, 44 characters). It is not a hardware screenshot; maps, microphone status, local time zone and transient phone messages may differ.

The right side shows the exact rendered_text supplied by the phone app, with alert ID and server receipt time. Until the phone integrates the report call, it correctly says display unconfirmed. Reports expire as connection evidence after 15 seconds. The SDK accepting an update is not proof the wearer saw it.

The glasses app sends these reports with `VITE_G2_REPORT_TOKEN` (the backend's `G2_REPORT_TOKEN`), only after the SDK accepts an update, plus a heartbeat every five seconds; it reports `failed` on an SDK failure and `cleared` when clearing expired content. The same token authorizes `POST /wearer`.

GET /g2/status is read by the dashboard and returns reporting_configured, fresh and report. POST /g2/display requires the separate shared token (503 when unset, 401 when incorrect), a nonempty alert_id up to 128 characters, rendered_text up to 2048 characters, and status sdk_accepted/failed/cleared. It retains the last report in memory for this single-device prototype. Restarting clears it. Use HTTPS for remote connections and never use the model API key as the report token. Configure VITE_SUMMARY_URL and the Even Hub network whitelist to the same reachable backend origin. A phone’s localhost does not refer to this computer.

## Render deployment

Use the root render.yaml Blueprint on branch main. It deploys the Docker backend and dashboard together, binds Render's PORT and runs one worker (latest alerts and phone reports are process-local). Free hosting can sleep after inactivity; restarts clear current state. This is a hackathon deployment, not durable incident storage.

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

OpenCV is a color heuristic. Gemini is optional and requires an API key and a model available to your account via `GEMINI_MODEL`. This project does not currently implement Llama or ElevenLabs. Drone telemetry is relative odometry unless `gps_tf` geo-referencing is running. The demo `/view.png` map is not geographic navigation; the wearer map (`/wearer/map.png`) is drawn from real GPS and annotation coordinates. A voice-report receiver (`POST /report`) is not implemented.
