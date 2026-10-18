# FireSight — LA Hacks 2026

Cloud deployment: [VM setup](cloud/README.md). QNX migration: [target boundary and requirements](qnx/README.md). The cloud package runs the relay and snapshot worker independently of a laptop; provisioning still requires Google Cloud access and cost approval.

For saving snapshots, pairing them with JSON, and integrating with `beagle_eyes`, see [the integration guide](docs/beagle-integration.md). It includes a live/file snapshot worker, an upstream adapter, and retrying multipart delivery to an AI endpoint.

Local video receiver for the FireSight prototype. Paste a **direct stream URL**, or let a sender publish video to your Mac. A native MediaMTX process relays video to RTSP for OpenCV and HLS for browser preview. No Docker or npm dependencies required.

## Run on your Mac

Requires Node.js 22+ and macOS or Linux (arm64/x64).

```sh
npm run setup
npm start
```

Open http://127.0.0.1:8787. Setup downloads MediaMTX v1.21.2 from its official GitHub release and verifies the release asset SHA-256 digest. Runtime files, source credentials, and binaries stay in the ignored `.runtime/` folder.

### A. Your teammate gives you a stream URL

Paste `rtsp://SOURCE:8554/live`, `rtmp://SOURCE/live`, or `https://SOURCE/live/index.m3u8`, then click **Connect source**. The receiver pulls that stream and exposes:

| Consumer | Local address |
| --- | --- |
| OpenCV / VLC | `rtsp://127.0.0.1:8554/firesight` |
| HLS playlist | `http://127.0.0.1:8888/firesight/index.m3u8` |
| Browser player | `http://127.0.0.1:8888/firesight/` |

The URL must serve media directly, not a YouTube page, dashboard URL, or ordinary MP4. HTTP(S) sources must have a `.m3u8` pathname. A successful configuration request means the address was accepted; **RECEIVING** means MediaMTX reports the stream ready. The preview may lag by several seconds. Relay readiness does not guarantee the browser supports the stream's codec. MediaMTX relays/remuxes; it does not transcode.

### B. Your teammate needs an address to send video to

Select **Receive a publisher → Enable receiver**. On the same Mac, publish to `rtmp://127.0.0.1:1935/firesight`. In OBS use server `rtmp://127.0.0.1:1935` and stream key `firesight`. Prefer H.264 video and AAC audio for browser compatibility.

For another device on the same Wi-Fi/LAN, stop the app and run:

```sh
MEDIA_BIND=0.0.0.0 npm start
```

The app shows your Mac's candidate LAN IPs. Replace `127.0.0.1` in the media addresses with the reachable LAN IP, e.g. `rtmp://192.168.1.42:1935/firesight`. The control app and MediaMTX API stay localhost-only. Media ports in LAN mode allow unauthenticated publishing/reading; use a trusted demo network. Do not open these ports to the public internet. Campus Wi-Fi client isolation or your firewall may block peer devices. LAN mode does not create a public/cloud endpoint.

Only one source is supported. Switching source/mode interrupts existing readers. Source settings reset to publisher mode when the app restarts. There is no recording.

## API

```sh
curl -X POST http://127.0.0.1:8787/api/source \
  -H 'Content-Type: application/json' \
  -d '{"url":"rtsp://CAMERA_IP:8554/live"}'

curl http://127.0.0.1:8787/api/status

curl -X POST http://127.0.0.1:8787/api/publisher \
  -H 'Content-Type: application/json' -d '{}'
```

Status includes `ready`, `relayRunning`, tracks, byte count, readers, and output URLs. Source URLs are deliberately excluded from status responses, and raw MediaMTX logs are not retained because URLs may contain credentials.

## OpenCV teammate

```sh
python -m pip install opencv-python
python examples/opencv_receiver.py rtsp://127.0.0.1:8554/firesight
```

Replace the host for another machine. The example reconnects after failures; press Q while the preview is focused to stop. Detection and hazard JSON submission are integration points, not implemented here.

## Test video without the drone

With FFmpeg installed, select publisher mode and send a generated test pattern:

```sh
ffmpeg -re -f lavfi -i testsrc2=size=640x360:rate=15 \
  -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p \
  -g 30 -an -f flv rtmp://127.0.0.1:1935/firesight
```

Or replace the input with `-re -stream_loop -1 -i test.mp4`. FFmpeg is only needed for a test publisher, not for normal relay use. DJI controller custom RTMP support must be confirmed on the actual hardware.

## Architecture

```text
Existing RTSP / RTMP / HLS source ──pull──┐
                                        ▼
                                  MediaMTX on Mac ──RTSP──▶ OpenCV
                                        │
Drone / OBS / FFmpeg ───RTMP publish──────┘──HLS──▶ Browser preview

Local control app :8787 ──configure/status──▶ MediaMTX API :9997
```

Use either pull or publish mode. The streaming relay is independent of the future hazard API, QNX supervisor, voice agent, and glasses bridge.

## Checks

`npm test` checks input validation and configuration injection handling. Test live ingest and decode with an actual source before handing off to teammates.

References: [MediaMTX configuration](https://mediamtx.org/docs/references/configuration-file), [installation](https://mediamtx.org/docs/kickoff/install), [project and license](https://github.com/bluenviron/mediamtx).

## Original main description

# firesight-la-hacks
FireSight: AI-powered drone intelligence for firefighters with a QNX safety supervisor
