# FireSight repository audit — October 18, 2026

This report follows executable code and freshly fetched remote branches, rather than README claims. No branches were merged and no application code was changed during this audit.

## Overall result

FireSight has working individual components, but the inspected code does not yet form a verified, continuous drone-to-glasses pipeline. The largest integration gap is between Greg's current Beagle Eyes broadcast protocol and the dashboard backend's remote receiver.

## Branch inventory

| Remote branch | Inspected commit | What it contains |
| --- | --- | --- |
| main | 239fa81 | Initial README only; not the assembled application. |
| vm-setup | 9c3617d | Original Node receiver controls, MediaMTX deployment, JPEG/JSON capture, delivery worker, and receiver smoke tests. |
| feature/video-to-json | 723fb07 | Python image/video analysis, OpenCV heuristic detection and Gemini integration. |
| glasses-app | d580798 | Even Hub glasses client, including map/voice client work. |
| feature/dashboard | 3a50a89 | Most integrated application: Python API, receiver watchers, vision, glasses client, Render deployment and map-first dashboard. |

The active checkout is feature/dashboard. Its map-first UI is committed. Local changes also remain in README.md, glasses-app/app.json, pyproject.toml and src/firesight/api.py, with an untracked design-preview directory and dashboard/mission.js. Those local changes must not be assumed to be deployed.

## Actual pipeline

```text
Drone → Greg's MediaMTX → Beagle Eyes / DPVO
                              ├─ MJPEG / snapshot JPEG
                              └─ WebSocket JSON telemetry + binary JPEG
                                      ↓
                              MISSING compatible adapter
                                      ↓
FireSight frame analysis → latest alert → Even Hub phone app → G2 SDK
                                  ↑                         ↓
                         dashboard ← display acknowledgement
```

The older VM path is separate: RTMP → MediaMTX → sampled JPEG/JSON bundles → local watcher or delivery worker. It does not run Greg's complete visual odometry pipeline.

## Greg's Beagle Eyes repository

Inspected remote main at 32062ed in sangregoriokimpo/beagle_eyes. Relevant code: scripts/uav_vo.py, broadcast/broadcaster.py and broadcast/useBeagleStream.ts.

- Receives drone video and runs DPVO visual odometry with its GPU/PyTorch dependencies.
- Serves /video.mjpg, /snapshot.jpg, /status, /health and WebSocket /ws on port 8765.
- Broadcasts position, quaternion, trajectory, timing metrics and a bounded point cloud as JSON, plus JPEGs as binary WebSocket messages.
- The inspected publishing hook sends raw camera frames before desktop display annotations. The desktop split-screen and annotated people boxes in the supplied screenshot are not automatically reproduced by consuming this JPEG stream.
- Telemetry is local visual-odometry position, not latitude/longitude. An explicit geographic origin, orientation and verified scale are needed to place it accurately on a street map.
- JPEG messages do not carry a matching frame ID envelope. Receiving a JPEG near a telemetry message does not establish exact frame correspondence.
- The supplied React stream hook is not wired into our vanilla-JavaScript dashboard.

## Python backend and analysis

Sources: src/firesight/api.py, live.py, frame.py, detector.py, vision.py, alerts.py, gemini.py, video.py and cli.py.

The FastAPI backend serves the dashboard, accepts images/video/alerts, maintains the latest alert in memory and records glasses display reports.

| Endpoint | Implemented behavior |
| --- | --- |
| GET /health | Health check. |
| GET /live | Watcher status and latest analyzed snapshot, metadata and alert. |
| POST /frame | Analyze an uploaded image and publish an alert. |
| POST /video | Sample an uploaded video and return one aggregate alert. |
| GET /latest | Latest alert, or no content when missing/stale. |
| POST /latest | Accept a precomputed alert. |
| POST /g2/display | Accept authenticated SDK display status. |
| GET /g2/status | Read the most recent display report. |

Local bundles use frame.jpg plus metadata.json, a UUID frame_id, ISO received_at timestamp and SHA-256 checksum. The remote watcher expects JSON containing that metadata and jpeg_base64. Greg's current WebSocket packets and MJPEG endpoint do not satisfy that contract.

POST /frame accepts an image but does not preserve the paired metadata or use Idempotency-Key. Consequently, the old delivery worker cannot yet guarantee matching source identity or duplicate suppression through that endpoint.

OpenCV detection is a color/region heuristic, not a trained fire VLM or person detector. Image analysis can instead select Gemini; auto mode chooses based on API-key presence, but a Gemini request failure does not automatically fall back to OpenCV. The configured default Gemini model name was not verified against a working service during this audit. Video analysis always uses the OpenCV path and returns an aggregate result rather than continuous alerts.

No implemented Llama inference service or ElevenLabs integration was found in the inspected application paths.

## Dashboard

Source: src/firesight/dashboard/index.html.

The committed dashboard provides a bright full-screen MapLibre map with floating panels, buildings, camera imagery and a glasses display panel. It polls /live and /g2/status approximately every 2.5 seconds.

The camera panel shows the latest analyzed snapshot, not Greg's continuous MJPEG feed. Illustrated fire areas and simulated drone motion are demonstrations, not geographically registered live detections. The supplied telemetry quaternion, trajectory and point cloud are not yet connected to a live 3D scene. The separate design-preview is local work, not evidence of the published application state.

## G2 glasses

Sources: glasses-app/src and its display tests.

The Even Hub client polls /latest, renders text through the SDK, checks SDK results and reports accepted/failed/cleared state to /g2/display. The dashboard can mirror the reported rendered text. This is an SDK acknowledgement, not a screenshot or proof that a wearer saw the message.

The client has optional map rendering, but the backend alert validation currently discards map_url and there is no connected map-image generator. Voice recording exists behind a feature flag, but posts to /report, which the inspected backend does not implement. It is not a completed voice assistant.

The client does not currently send wearer location. The installed SDK exposes phone-app location methods, but permission handling, continuous location updates, an authenticated backend endpoint and map updates still need implementation. This would represent the phone/wearer location, not the drone location.

## VM and deployment

The vm-setup branch contains a useful alternative capture stack and synthetic receiver tests. Its headless capture produces image bundles without running DPVO. Delivery retries are at least once; downstream consumers need deduplication. The newly added .gitmodules file does not make vendor/beagle_eyes a proper submodule: the inspected tree entry is still an ordinary directory rather than a gitlink.

Render configuration points to feature/dashboard, uses a Python Docker image and one Uvicorn worker, and configures the OpenCV detector. There is no GPU service or database in this configuration. In-memory alert/display state is lost on restart.

During this audit, the deployed /live response reported state=not_configured, configured=false, processed=0 and snapshot=null. That establishes that the deployed receiver was not receiving/analyzing a configured source at the time checked; it does not prove which commit is running.

Public-deployment write routes have ingest-token protection and upload limits. Read routes expose the latest frame/metadata/display text, and Greg's inspected broadcaster has no authentication. Access design must be addressed before adding private wearer-location data to public responses.

## Verification and limits

- Python watcher test suite: 1 test passed, exercising multiple frames, deduplication, checksum and stale-input handling.
- Glasses display tests: 3 passed with mocked SDK behavior.
- Deployed /live checked read-only.
- No live drone, physical glasses, Gemini request or VM smoke test was run during this audit. Earlier synthetic VM results do not establish the current complete integration.

## Recommended implementation order

1. Agree on Greg's exact live contract, including how each JPEG relates to telemetry; implement the WebSocket adapter or a shared bundle endpoint.
2. Separate continuous camera/telemetry updates from slower, bounded AI inference. Show source age and disconnect state.
3. Preserve frame identity and metadata through analysis; add duplicate handling for retried deliveries.
4. Select and test the actual detector/model. Keep image-sector instructions distinct from geographic navigation.
5. Verify one real alert reaches G2 and its SDK acknowledgement returns to the dashboard.
6. Add authenticated phone-location sharing and geographic calibration for the drone as separate features.
7. Complete map-image and voice paths only if they remain in scope.
8. Review and consolidate branches into main, then deploy and run a continuous end-to-end test.

QNX currently has documentation/planning in the VM branch, not an implemented runtime component. It is not required for the existing Python/Render/Even Hub path.
