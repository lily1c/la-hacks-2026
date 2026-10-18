"""Durable image + JSON handoff. OpenCV is imported only when encoding a frame."""
import hashlib
import json
import math
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request


class FrameBridge:
    def __init__(self, directory, stream_id='firesight', interval=1.0):
        if not math.isfinite(interval) or interval < 0:
            raise ValueError('interval must be finite and nonnegative')
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.stream_id = stream_id
        self.session_id = str(uuid.uuid4())
        self.interval = interval
        self.last_saved = -math.inf

    def save(self, frame, source_sequence, context=None, received_at=None):
        """Call with the unannotated image; context is associated, not frame-accurate pose."""
        now = time.monotonic()
        if now - self.last_saved < self.interval:
            return None
        import cv2
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise ValueError('JPEG encoding failed')
        record = self.save_jpeg(encoded.tobytes(), int(frame.shape[1]), int(frame.shape[0]), source_sequence, context, received_at)
        self.last_saved = now
        return record

    def save_jpeg(self, jpeg, width, height, source_sequence, context=None, received_at=None):
        if not jpeg.startswith(b'\xff\xd8') or not jpeg.endswith(b'\xff\xd9'):
            raise ValueError('JPEG bytes required')
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise ValueError('Positive image dimensions required')
        frame_id = str(uuid.uuid4())
        record = {
            'schema_version': 'firesight.frame.v1',
            'frame_id': frame_id, 'session_id': self.session_id,
            'stream_id': self.stream_id, 'source_sequence': int(source_sequence),
            'received_at': received_at or datetime.now(timezone.utc).isoformat(),
            'timestamp_basis': 'receiver_observation_time_not_drone_capture_time',
            'image': {'filename': 'frame.jpg', 'mime_type': 'image/jpeg', 'width': width, 'height': height,
                      'sha256': hashlib.sha256(jpeg).hexdigest()},
            'context': context or {},
        }
        serialized = json.dumps(record, allow_nan=False, indent=2)
        staging = self.directory / ('.' + frame_id)
        staging.mkdir()
        try:
            (staging / 'frame.jpg').write_bytes(jpeg)
            (staging / 'metadata.json').write_text(serialized)
            staging.rename(self.directory / frame_id)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return record


def bundles(directory):
    """Only completed pairs are visible; no half-written images or JSON."""
    result = []
    for folder in Path(directory).expanduser().glob('*'):
        if folder.name.startswith('.') or not folder.is_dir():
            continue
        if (folder / 'metadata.json').is_file() and (folder / 'frame.jpg').is_file():
            result.append(folder)
    return sorted(result, key=lambda folder: (folder / 'metadata.json').stat().st_mtime_ns)


def deliver(folder, endpoint, token=None):
    """At-least-once multipart delivery. Receiver must deduplicate by frame_id."""
    folder = Path(folder)
    metadata = (folder / 'metadata.json').read_bytes()
    record = json.loads(metadata)
    image = (folder / 'frame.jpg').read_bytes()
    if hashlib.sha256(image).hexdigest() != record['image']['sha256']:
        raise ValueError('Image checksum does not match metadata')
    boundary = 'firesight-' + uuid.uuid4().hex
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\nContent-Type: application/json\r\n\r\n'.encode()
        + metadata
        + f'\r\n--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="frame.jpg"\r\nContent-Type: image/jpeg\r\n\r\n'.encode()
        + image + f'\r\n--{boundary}--\r\n'.encode()
    )
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}', 'Idempotency-Key': record['frame_id']}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = Request(endpoint, data=body, headers=headers, method='POST')
    # Do not follow redirects: credentials and image data must stay at the configured destination.
    from urllib.request import HTTPRedirectHandler, build_opener
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    with build_opener(NoRedirect()).open(request, timeout=15) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError('Downstream did not acknowledge the frame')
    (folder / 'delivered').write_text(datetime.now(timezone.utc).isoformat())


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Forward saved image + JSON bundles to an AI endpoint')
    parser.add_argument('--directory', default=os.environ.get('FRAME_DIR', '.runtime/frame-bundles'))
    parser.add_argument('--endpoint', default=os.environ.get('AI_ENDPOINT'))
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if not args.endpoint:
        parser.error('--endpoint or AI_ENDPOINT is required')
    from urllib.parse import urlsplit
    target = urlsplit(args.endpoint)
    if target.scheme not in ('http', 'https') or not target.hostname or target.username or target.password:
        parser.error('Use an HTTP(S) endpoint without URL credentials')
    while True:
        for folder in bundles(args.directory):
            if (folder / 'delivered').exists():
                continue
            try:
                deliver(folder, args.endpoint, os.environ.get('AI_TOKEN'))
                print('Delivered', folder.name, flush=True)
            except Exception as error:
                print('Delivery failed; bundle retained for retry:', type(error).__name__, flush=True)
                break
        if args.once:
            return
        time.sleep(2)


if __name__ == '__main__':
    main()
