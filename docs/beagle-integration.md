# Video → image + JSON → AI integration

Inspected upstream `sangregoriokimpo/beagle_eyes` commit `7af438bc2294fad090e7329a53a40eb2791d9a41`.

## What the existing code does

`scripts/uav_vo.py` starts a local MediaMTX server, reads RTMP through FFmpeg, decodes JPEGs with OpenCV, and runs DPVO visual odometry. Its default path is `/live/dji`. `save_jpegs` optionally writes images, but it exports no JSON and has no downstream API. DPVO dependencies are declared as the Git submodule `vendor/Deep-Visual-Odometry-SLAM`, pinned to `f2431991c26f22308b6aed268ca897ad76039409`; its contents are not included in the source snapshot. The existing model requires its own working inference environment; it is not a hazard detector.

## Shared architecture

```text
Drone / compatible RTMP sender
       │ rtmp://VM_PUBLIC_IP:1935/live/dji (publishing credentials required)
       ▼
Cloud VM — MediaMTX
       ├─ Continuous RTMP → teammate's working Beagle Eyes / DPVO environment
       │                      └─ integrated exporter → JPEG + JSON bundles
       └─ RTSP → CPU snapshot worker → JPEG + JSON bundles (no odometry yet)
                                         │
                                  Retrying delivery worker
                                         │ multipart POST
                                         ▼
                               AI/OpenCV service /frames
                                         └─ hazard JSON with same frame_id
```

The CPU snapshot worker and Beagle exporter are alternative bundle producers. Do not merge their records based solely on frame number or approximate wall-clock time: independent readers sample different frames. For image+odometry, use Beagle's own exporter to keep the context and actual processed image together. For later sensors/other repos, propagate the shared frame_id or define explicit synchronization rules.

## Start without the drone or GPU

Install `opencv-python` (already available in this development environment), then:

```sh
python scripts/capture_frames.py --source test.mp4 --file --interval 0 --max-frames 3
```

Each completed bundle is published atomically:

```text
.runtime/frame-bundles/<frame_id>/
  frame.jpg
  metadata.json
  delivered          # appears only after an HTTP 2xx acknowledgment
```

For live video:

```sh
python scripts/capture_frames.py --source rtsp://VM_ADDRESS:8554/live/dji --interval 1
```

Only URLs reachable from the worker will work. This does not provision a VM. The worker consumes the stream continuously but saves at most one frame per interval, reconnects after disconnects, and writes unannotated images. Repeated network errors can produce OpenCV stderr that includes the stream URL; keep runtime logs private when embedding credentials.

## Integrate into the other repo without overwriting it

On the teammate's existing working Beagle machine:

```sh
python /path/to/la-hacks-2026/scripts/prepare_beagle_integration.py /path/to/beagle_eyes
```

This generates `scripts/uav_vo_firesight.py` and copies `frame_bridge.py` alongside it. It refuses an existing generated script and checks upstream insertion points. The original `uav_vo.py` stays unchanged. Run the new script with the existing environment and weights:

```sh
FRAME_DIR=/path/to/shared/frame-bundles python scripts/uav_vo_firesight.py --config config/uav_config.yaml
```

For a cloud relay, set these values in your own copy of `uav_config.yaml`:

```yaml
mediamtx:
  auto_start: false
rtmp:
  mode: pull
  url_override: "rtmp://reader:PASSWORD@VM_ADDRESS:1935/live/dji"
network:
  auto_configure_static_ip: false
```

Merge these values into the existing config; do not replace all the camera/model settings. The generated script honors `auto_start: false` by skipping local server startup. This avoids the upstream startup code restarting a local MediaMTX process. Do not run the upstream static-IP setup script on the cloud VM.

## What the AI teammate receives

The delivery process POSTs `multipart/form-data` with `image` (JPEG bytes) and `metadata` (JSON). `Idempotency-Key` is the frame_id. Example metadata:

```json
{
  "schema_version": "firesight.frame.v1",
  "frame_id": "unique-uuid",
  "session_id": "unique-process-session-uuid",
  "stream_id": "firesight",
  "source_sequence": 42,
  "received_at": "2026-10-17T23:00:00+00:00",
  "timestamp_basis": "receiver_observation_time_not_drone_capture_time",
  "image": {
    "filename": "frame.jpg", "mime_type": "image/jpeg",
    "width": 1280, "height": 720, "sha256": "image-content-sha256"
  },
  "context": {"producer": "beagle_eyes", "odometry_initialized": false}
}
```

After initialization, Beagle bundles can include `context.latest_keyframe_pose`. This is the latest available keyframe's camera-to-world pose; it is **not necessarily the current image's pose**. Monocular translation is labeled `arbitrary_monocular_scale`, not meters. Initialization does not fabricate a zero pose. Image and JSON share an identity and checksum; this does not imply sensor-level timestamp synchronization.

Configure the AI endpoint and start delivery only after the destination has been agreed with the AI teammate:

```sh
export AI_ENDPOINT=https://YOUR_AI_SERVICE/frames
export AI_TOKEN=YOUR_SERVICE_TOKEN
python integrations/beagle_eyes/frame_bridge.py --directory .runtime/frame-bundles
```

No destination is configured and nothing is sent automatically. Failed requests retain the bundle for retry. Successful bundles remain on disk for debugging. The receiving service must durably store or enqueue the work before returning 2xx and deduplicate repeated frame_ids; delivery is at least once. One failing bundle blocks later delivery until fixed. Run one sender per directory. Add retention/quotas before long-running use because images currently accumulate on disk.

The AI service should store its output keyed by frame_id, e.g. `{"frame_id":"…","hazards":[…]}`. A 2xx acknowledgment means accepted, not that AI inference completed. Hazard detection and result callbacks belong to the AI teammate's service and are not implemented here.

## Verification

```sh
python -m unittest discover -s tests -p 'test_*.py'
npm test
```

Full DPVO inference requires the teammate's environment and drone/controller compatibility remains unverified. No VM, public publishing address, or deployed AI endpoint has been created by this integration.
