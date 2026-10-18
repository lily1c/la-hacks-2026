# Stable API contracts

`POST /ingest/beagle`: bearer INGEST_TOKEN is always required. Set INGEST_MODE=push. JSON contains session_id (UUID), telemetry (object with increasing integer frame_id and Unix-seconds timestamp), jpeg_base64 and sha256. Sender must pair the exact image with its telemetry. New frames return 202; duplicate/out-of-order frames return 200 accepted=false. Bad data returns 422; wrong token 401; disabled push mode 503. Receiver limits payload to 12 MiB and JPEG to 8 MiB; source age must be 0–30 seconds. Deduplication is bounded and in memory.

`GET /live`: fresh snapshot with frame_id, metadata (including original telemetry), image data URL and nullable alert. New images may appear before inference completes. `processed` counts analyzed frames; intermediate frames may be skipped. Missing/stale data has no fresh snapshot.

`GET /latest`: current id, timestamp, priority, headline and instructions. Optional demo map_url when FIRESIGHT_DEMO_MAP=true. Returns 204 for absent/expired alerts. Alert ID equals the analyzed bundle ID for push ingestion.

`POST /g2/display`: bearer G2_REPORT_TOKEN, alert_id, rendered_text, status sdk_accepted|failed|cleared. `GET /g2/status` returns the report and freshness. This confirms an SDK response, not wearer perception.

Legacy POST /frame, /video and /latest remain supported. With PUBLIC_DEPLOYMENT=true they require INGEST_TOKEN. Legacy /frame is image-only and does not establish telemetry pairing. /video produces an aggregate OpenCV alert.

No /report voice endpoint or wearer-location endpoint is implemented.
