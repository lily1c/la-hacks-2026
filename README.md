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
