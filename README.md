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

## Setup and verification

- [Greg's sender](integrations/beagle_push/README.md)
- [Glasses setup](docs/glasses-setup.md)
- [Architecture and branch decisions](docs/architecture.md)
- [API contracts](docs/api-contracts.md)
- [Testing](docs/testing.md)
- [Demo instructions](docs/demos.md)

Render uses `render.yaml`, targeting `main`. An existing manually configured Render service may still require its branch setting to be changed in the dashboard. Keep existing tokens unchanged when deploying.

OpenCV is a color heuristic. Gemini is optional and requires an API key and a model available to your account via `GEMINI_MODEL`. This project does not currently implement Llama or ElevenLabs. Telemetry is relative odometry, not GPS. Generated demo maps are not geographic navigation. Phone GPS and voice-report backend support remain separate work.
