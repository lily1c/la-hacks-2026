"""Headless Beagle Eyes JPEG reader → matching metadata; no DPVO required."""
import argparse
import os
import shutil
import signal
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'integrations/beagle_eyes'))
from frame_bridge import FrameBridge
from jpeg_stream import RTMPJpegStream


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=os.environ.get('STREAM_URL'))
    parser.add_argument('--directory', default=os.environ.get('FRAME_DIR', '.runtime/frame-bundles'))
    parser.add_argument('--max-frames', type=int, default=0)
    args = parser.parse_args()
    if not args.source or not shutil.which('ffmpeg'):
        parser.error('STREAM_URL (or --source) and ffmpeg are required')
    bridge = FrameBridge(args.directory)
    stream = RTMPJpegStream({'url_override': args.source, 'fps': 1,
                            'width': 1280, 'height': 720, 'save_jpegs': False,
                            'probesize': 1000000, 'analyzeduration': 1000000}, '127.0.0.1')
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    seq = saved = 0
    stream.start()
    try:
        while not stopping:
            seq, frame, jpeg = stream.read_latest(seq)
            if frame is not None:
                record = bridge.save_jpeg(jpeg, frame.shape[1], frame.shape[0], seq,
                                         {'producer': 'beagle_eyes_jpeg', 'odometry_initialized': False})
                if record:
                    saved += 1
                    print('Saved', record['frame_id'], flush=True)
                if args.max_frames and saved >= args.max_frames:
                    break
            time.sleep(0.05)
    finally:
        stream.stop()


if __name__ == '__main__':
    main()
