"""Sample a live stream or a local test video to durable JPEG + JSON bundles."""
import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integrations' / 'beagle_eyes'))
from frame_bridge import FrameBridge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=os.environ.get('STREAM_URL', 'rtsp://127.0.0.1:8554/firesight'))
    parser.add_argument('--directory', default=os.environ.get('FRAME_DIR', '.runtime/frame-bundles'))
    parser.add_argument('--interval', type=float, default=1.0)
    parser.add_argument('--max-frames', type=int, default=0)
    parser.add_argument('--file', action='store_true', help='Read a local test video and exit at EOF')
    args = parser.parse_args()
    os.environ.setdefault('OPENCV_FFMPEG_CAPTURE_OPTIONS', 'rtsp_transport;tcp')
    import cv2
    bridge = FrameBridge(args.directory, interval=args.interval)
    saved = sequence = 0
    while True:
        if args.file:
            cap = cv2.VideoCapture(args.source)
        else:
            cap = cv2.VideoCapture(args.source, cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
        try:
            if args.file and not cap.isOpened():
                raise RuntimeError('Cannot open the local video file')
            while cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    break
                sequence += 1
                record = bridge.save(frame, sequence, received_at=datetime.now(timezone.utc).isoformat())
                if record:
                    saved += 1
                    print('Saved', record['frame_id'], flush=True)
                if args.max_frames and saved >= args.max_frames:
                    return
        finally:
            cap.release()
        if args.file:
            return
        print('Stream unavailable; retrying in 2 seconds', flush=True)
        time.sleep(2)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
