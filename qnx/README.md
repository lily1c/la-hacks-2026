# QNX migration boundary

The cloud VM is a Linux media host, not a QNX target. The current repository has **not** been compiled or tested on QNX. An eventual full migration requires a QNX SDP/toolchain, the exact target hardware/image, and confirmed dependencies and drivers.

Initial architecture:

```text
Linux VM: RTMP relay → snapshot extraction → durable JPEG + JSON → AI service
                                                                    │
                                                hazard JSON + heartbeat
                                                                    ▼
QNX target: receive → validate → prioritize → watchdog → alert output
```

Keep `frame_id`, `stream_id`, and `session_id` in AI results. Define alert and heartbeat messages before implementing the QNX transport; use monotonic receiver time for watchdog deadlines and UTC only for correlation. An image timestamp is receiver observation time, not guaranteed camera capture time. Latest Beagle keyframe pose is context rather than an exact pose for the exported image, and its translation has unknown monocular scale.

Suggested later hazard envelope (contract proposal; no QNX receiver is implemented):

```json
{
  "schema_version": "firesight.alert.v1",
  "type": "hazard",
  "frame_id": "frame-uuid",
  "stream_id": "firesight",
  "session_id": "producer-session-uuid",
  "severity": "critical",
  "message": "Potential smoke detected",
  "produced_at": "2026-10-17T23:00:00Z",
  "ttl_ms": 3000
}
```

Before moving *all* processing to QNX, verify:

- Media ingestion and JPEG encoding: MediaMTX runtime/Go support or a target-supported replacement; FFmpeg/GStreamer codec and licensing availability.
- Frame API/storage: target filesystem capacity, retention policy, TCP/TLS libraries, and matching JSON schemas.
- Computer vision: target-specific OpenCV build and required modules. Python Linux wheels cannot be reused unchanged.
- DPVO: PyTorch/custom extensions and GPU/runtime support for the actual target. A working Linux inference machine is not evidence of QNX support.
- Headless execution: upstream Beagle uses `cv2.imshow`; remove its GUI dependency for servers/targets.
- QNX scheduling: benchmark priority handling and watchdog deadlines on the actual target. Cloud/network latency cannot be guaranteed by a local real-time scheduler.

If a full QNX port is required, make feasibility checks the next milestone before committing to it. A QNX supervisor with Linux-hosted vision remains a practical initial integration, but is distinct from all processing on QNX.

Official target references: [QNX Raspberry Pi 4 BSP](https://www.qnx.com/developers/docs/BSP8.0/com.qnx.doc.bsp.releasenotes/topic/rel_sdp80.bsp.broadcom.rpi4.bcm2711.html), [Quick Start target images](https://www.qnx.com/developers/docs/qnxeverywhere/com.qnx.doc.target_images/topic/qsti/install.html).
