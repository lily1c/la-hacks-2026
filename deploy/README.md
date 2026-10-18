# Continuous receiver dashboard

This service runs beside the existing RTMP receiver. It does not replace MediaMTX or open a second RTMP listener. Set BUNDLE_DIRECTORY to the existing VM's absolute la-hacks-2026/cloud/data/bundles path, then run:

```
BUNDLE_DIRECTORY=/absolute/path/to/la-hacks-2026/cloud/data/bundles docker compose -f deploy/compose.yaml up -d --build
```

The mount is read-only; the watcher never deletes receiver files. It expects completed frame.jpg + metadata.json directories in firesight.frame.v1 format, as produced by the current VM receiver. It is not an arbitrary DJI telemetry parser. Inference uses the existing analyze_frame function (OpenCV by default, or Gemini when explicitly configured). Run one API worker. /live returns the latest fresh analyzed JPEG, matching metadata, alert and worker status. /latest remains the glasses contract. Samples older than 30 seconds are skipped; invalid pairs are rejected. Newest-first sampling deliberately skips intermediate frames when analysis is slower than capture.

The dashboard listens on VM localhost:8790. Use an SSH tunnel to view it; public hosting still needs authentication and HTTPS. Model API keys belong in server environment variables only. Existing capture storage limits remain active: configure receiver retention separately for long-running operation; this service does not acknowledge the old external-delivery queue or clean it up.

For local development:

```
FRAME_DIR=/absolute/path/to/bundles FIRESIGHT_DETECTOR=opencv PYTHONPATH=src uvicorn firesight.api:app --host 127.0.0.1 --port 8790
```

Manual image uploads remain available. Follow drone restores automatic matching-frame display. An API connection is not proof that the drone is connected; the separate receiver indicator and freshness are required.
