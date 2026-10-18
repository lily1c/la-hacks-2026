# Greg → hosted FireSight

Beagle Eyes stays on Greg's local GPU computer. Only outgoing HTTPS is required; do not expose his local server or configure a tunnel for this path.

## Backend (Render)

Set `INGEST_MODE=push` and keep `INGEST_TOKEN` set to a private shared value. Deploy the integration commit. Existing `/latest` and `/g2/display` keep working. Push mode replaces the old FRAME_DIR/BEAGLE_URL watcher; do not expect both inputs at once.

## Greg's setup

Copy `sender.py` beside the capture script. Set `FIRESIGHT_URL=https://firesight-dashboard.onrender.com` and `INGEST_TOKEN` to the backend's ingest token privately (never commit it).

Create one `FireSightSender` when the program starts:

```python
from sender import FireSightSender
sender = FireSightSender()
```

At the point where a frame and its telemetry have BOTH been computed:

```python
sender.submit(jpeg_bytes, telemetry)
```

`jpeg_bytes` must be the JPEG for that exact telemetry frame, not a later mutable camera buffer. Telemetry must contain an increasing integer `frame_id` and current Unix-seconds `timestamp`. Keep pose, trajectory and point_cloud in the same telemetry object. If DPVO pose is from a prior keyframe, explicitly describe that in telemetry; do not claim it is a new measured pose. Start a new sender instance when frame numbering restarts. Keep system clocks synchronized.

The sender uses a background thread with one pending frame, caps uploads at two per second, and retries briefly. No CUDA is needed by the sender; Greg's existing DPVO still needs its own dependencies. The sender is a single-producer helper for the capture loop.

Each upload contains session_id, telemetry, jpeg_base64 and sha256. The backend derives a stable UUID from session + source frame ID. Duplicate/older frames are ignored; session deduplication is in-memory and bounded, not durable across backend restarts. Maximum JPEG size is 8 MiB; request limit 12 MiB. Frames older than 30 seconds are rejected. JPEG decoding occurs during analysis; malformed images do not produce alerts.

## Check the connection

1. Start Greg's capture loop and confirm no upload errors.
2. GET `/live`: expect source `beagle_push`, fresh=true, and changing snapshot.frame_id and metadata.source_frame_id.
3. Compare metadata.telemetry with Greg's source packet. The image and metadata appear before analysis finishes.
4. GET `/latest`: after analysis, alert.id must match an uploaded frame ID. Analysis may skip intermediate frames to avoid lag.
5. Verify the phone displays that alert and `/g2/status` reports its ID.
6. Stop the sender: `/live` must stop reporting fresh after 30 seconds.

Current public dashboard read endpoints expose imagery and telemetry. Use non-sensitive demo data; wearer-location access control is separate work. This integration has automated receiver tests, but still requires Greg's source hook and a real deployment smoke test.
