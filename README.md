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

## Dashboard

With the API running, open http://localhost:8787/ to upload a JPEG/PNG, analyze it using the configured detector, inspect the latest alert and its JSON, and preview the G2 text. The dashboard polls `/latest` and keeps up to 20 alerts in memory for the current browser session. Alerts older than 15 seconds are labeled stale. The image preview is your uploaded file, not a live drone stream or necessarily the source of an incoming alert. G2 delivery is not confirmed by this preview. No frontend build is required. Use this with the local API; public hosting requires authentication and upload limits.

## Connect Greg’s Beagle Eyes app (later)

The dashboard does not require the old VM. Greg’s computer receives the drone RTMP stream and runs Beagle/DPVO. This backend requests paired camera frames and relative coordinates from that running application. GitHub stores the code; it is not the live data endpoint.

**Leave BEAGLE_URL unset for now.** With neither BEAGLE_URL nor FRAME_DIR configured, the dashboard shows an empty frame area and unavailable coordinates. No drone frames or positions are fabricated.

### 1. Enable export on Greg’s computer

Copy this dashboard project onto Greg’s computer alongside his working beagle_eyes checkout. From this project, run:

```sh
python3 integrations/beagle/install_adapter.py /absolute/path/to/beagle_eyes
```

This creates scripts/uav_vo_dashboard.py and scripts/firesight_export.py in his checkout, preserving the original uav_vo.py. It refuses to overwrite an existing adapter and stops if the source insertion points changed. Use Greg’s existing working Python/DPVO environment and configuration.

Set a private token in the terminal (use the same value on both computers; never commit it):

```sh
export BEAGLE_EXPORT_TOKEN='YOUR_PRIVATE_SHARED_TOKEN'
# Default bind is localhost. On a trusted shared LAN only:
export BEAGLE_EXPORT_BIND=0.0.0.0
cd /absolute/path/to/beagle_eyes
python scripts/uav_vo_dashboard.py --config config/uav_config.yaml
```

The adapter exposes GET /snapshot on port 8791. It requires an Authorization: Bearer header and exports at most two snapshots per second. Each response contains matching JPEG bytes, metadata, frame ID, observation timestamp, checksum and, when initialized, latest keyframe translation. It returns 204 after five seconds without a new exported frame. It does not export the point cloud or run hazard analysis.

### 2. Find the address and connect this backend

On Greg’s Linux computer, `hostname -I` lists local IP addresses. Choose the address reachable from the dashboard backend (typically both computers on the same Wi-Fi). Campus Wi-Fi can block peer traffic. Use a private tunnel if needed. Do not expose unencrypted token-bearing HTTP on the public internet; use HTTPS or an SSH tunnel. For an SSH tunnel, keep export bound to localhost and forward local port 8791 to Greg’s localhost:8791.

On the computer running this dashboard:

```sh
export BEAGLE_URL='http://GREG_REACHABLE_IP:8791/snapshot'
export BEAGLE_EXPORT_TOKEN='THE_SAME_PRIVATE_SHARED_TOKEN'
export FIRESIGHT_DETECTOR=opencv
PYTHONPATH=src uvicorn firesight.api:app --host 127.0.0.1 --port 8790
```

Open http://127.0.0.1:8790/ and select **Follow drone**. The backend polls Greg, verifies each pair, analyzes the newest frame using the existing detector, and exposes it to the dashboard at /live. /latest keeps the G2 alert format and uses the original frame ID. Slow inference skips intermediate frames; this is a sampled view, not a full-frame-rate video player. Both computers’ clocks should be synchronized; frames older than 30 seconds are rejected.

To use the existing Gemini code, configure GEMINI_API_KEY, FIRESIGHT_DETECTOR=gemini and a provider-supported GEMINI_MODEL in the backend environment. No keys belong in the browser. The screenshot's X/Z/Alt panel is visual odometry, not GPS. This dashboard displays X/Y/Z as arbitrary-scale relative coordinates associated with the latest keyframe; it does not claim meters, exact current-frame pose, safe paths or wearer position. While Beagle initializes, coordinates remain unavailable.

### 3. Verify the live connection

Confirm the receiver status changes to receiving from Beagle, frame IDs change, image and metadata match, and positions appear only after DPVO initialization. Stop Greg’s exporter and confirm the dashboard marks the connection unavailable and clears expired image/position data. G2 delivery and real drone inference must still be tested separately.

The adapter has been source-checked against Greg’s repository, but running his full GPU/DPVO application is still an on-device integration test. There is no configured Greg endpoint in this checkout.

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
