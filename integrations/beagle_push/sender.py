"""Copy beside Greg's script; submit the JPEG and telemetry from the same frame."""
import base64
import hashlib
import json
import os
import queue
import threading
import time
import uuid
from urllib.request import Request, urlopen


class FireSightSender:
    def __init__(self):
        self.url = os.environ['FIRESIGHT_URL'].rstrip('/') + '/ingest/beagle'
        if not self.url.startswith(('https://', 'http://127.0.0.1', 'http://localhost')):
            raise ValueError('FIRESIGHT_URL must use HTTPS (or localhost HTTP)')
        self.token = os.getenv('INGEST_TOKEN', '')
        self.session = str(uuid.uuid4())
        self.queue = queue.Queue(maxsize=1)
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, jpeg_bytes, telemetry):
        # Serialization freezes telemetry before the capture loop mutates it.
        payload = json.dumps({'session_id': self.session, 'telemetry': telemetry,
                              'jpeg_base64': base64.b64encode(jpeg_bytes).decode(),
                              'sha256': hashlib.sha256(jpeg_bytes).hexdigest()}, allow_nan=False).encode()
        try:
            self.queue.get_nowait()
        except queue.Empty:
            pass
        self.queue.put_nowait(payload)

    def _run(self):
        while True:
            payload = self.queue.get()
            for attempt in range(3):
                request = Request(self.url, data=payload, headers={
                    'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token})
                try:
                    with urlopen(request, timeout=10) as response:
                        response.read()
                    break
                except Exception as error:
                    print('FireSight upload failed:', type(error).__name__, flush=True)
                    if not self.queue.empty():
                        break  # Prefer a newer frame to retrying old footage.
                    time.sleep(attempt + 1)
            time.sleep(0.5)  # At most two uploads per second.
