# Stable API contracts

`POST /ingest/beagle`: bearer INGEST_TOKEN is always required. Set INGEST_MODE=push. JSON contains session_id (UUID), telemetry (object with increasing integer frame_id and Unix-seconds timestamp), jpeg_base64 and sha256. Sender must pair the exact image with its telemetry. New frames return 202; duplicate/out-of-order frames return 200 accepted=false. Bad data returns 422; wrong token 401; disabled push mode 503. Receiver limits payload to 12 MiB and JPEG to 8 MiB; source age must be 0–30 seconds. Deduplication is bounded and in memory.

`GET /live`: fresh snapshot with frame_id, metadata (including original telemetry), image data URL and nullable alert. New images may appear before inference completes. `processed` counts analyzed frames; intermediate frames may be skipped. Missing/stale data has no fresh snapshot.

`GET /latest`: current id, timestamp, priority, headline and instructions. Optional demo map_url when FIRESIGHT_DEMO_MAP=true. Returns 204 for absent/expired alerts. Alert ID equals the analyzed bundle ID for push ingestion.

`POST /g2/display`: bearer G2_REPORT_TOKEN, alert_id, rendered_text, status sdk_accepted|failed|cleared. `GET /g2/status` returns the report and freshness. This confirms an SDK response, not wearer perception.

Legacy POST /frame, /video and /latest remain supported. With PUBLIC_DEPLOYMENT=true they require INGEST_TOKEN. Legacy /frame is image-only and does not establish telemetry pairing. /video produces an aggregate OpenCV alert.

`POST /wearer`: bearer G2_REPORT_TOKEN (the same token as display reports), JSON lat, lon, optional device_id (default `g2`), accuracy_m, heading_deg, speed_mps. Returns `nearby`: up to 3 mapped annotations sorted by distance, each with label, kind, severity, distance_m, bearing_deg, compass and approx. The same report may carry glasses telemetry: `device` (worn, battery, charging, in_case, imu_on, imu_events), `imu` (up to 120 samples `[unix ms, x, y, z]`, accelerometer in g with z up when the head is upright), `inputs` (button presses: type click/double_click/scroll_up/scroll_down/long_press/long_press_release, source right/left/ring), `status` (ok, check, man_down, sos) and `ack` (`alert_id` the wearer acknowledged). When hazards are mapped, the reply also has `situation` (an alert built from GPS) and `map_url` (`GET /wearer/map.png`, a north-up map around the wearer). `GET /wearer` returns wearers seen in the last 30 seconds with their telemetry, IMU statistics and a derived `motion` state (still, walking, tilted). Positions are kept in memory only; like the other read endpoints, GET /wearer is public.

No /report voice endpoint is implemented.
