# FireSight

FireSight takes a drone video, samples frames with OpenCV, encodes each sampled frame as JPEG, detects fire-colored regions, and publishes a compact alert for the glasses app.

## Project layout

```text
src/firesight/
  alerts.py      alert contract and validation
  api.py         upload and latest-alert HTTP routes
  cli.py         command-line entry point
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

The API allows cross-origin requests and exposes:

- `GET /latest` — `204 No Content` before an alert exists; otherwise `200 OK` with `Content-Type: application/json`.
- `POST /video` — upload a video as multipart field `video`; it analyzes frames, publishes the alert, and returns it.
- `POST /latest` — publish a prepared alert, useful for connecting an upstream LLM or exercising the glasses UI.
- `GET /health` — simple readiness check.

Example upload and poll:

```sh
curl -X POST 'http://localhost:8787/video?sample_seconds=1' \
  -F 'video=@path/to/drone_video.mp4' \
  -H 'Origin: https://glasses-app.example'

curl -i http://localhost:8787/latest
```

The video route samples one frame per second by default. It returns one alert based on the sampled frame with the strongest detected fire signal. The uploaded temporary video is deleted after analysis.

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

The video heuristic only knows image position. It cannot infer safe paths, distances, crew locations, or compass directions, so generated instructions identify frame sectors and should not be treated as evacuation guidance. An upstream model can publish richer instructions through `POST /latest` when it has trusted location and operational data.

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

The installed CLI writes the same alert JSON next to the video:

```sh
firesight-analyze path/to/drone_video.mp4 --sample-seconds 0.5 --out alert.json
```

The root-level `wildfire_analyzer.py` remains as a compatibility launcher for existing commands.

Detections use a single-frame color and brightness heuristic. Warm-colored objects can be false positives; results are not a verified fire assessment. Video/container support depends on the codecs available in the local OpenCV build.
