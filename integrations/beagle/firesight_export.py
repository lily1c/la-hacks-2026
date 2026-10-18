"""Copy next to Greg's UAV script. Exposes a bounded latest-frame HTTP snapshot."""
import base64
from datetime import datetime, timezone
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
import uuid


class FireSightExport:
    def __init__(self):
        self.token = os.environ.get('BEAGLE_EXPORT_TOKEN', '')
        if not self.token:
            raise ValueError('Set BEAGLE_EXPORT_TOKEN before enabling export')
        self.lock = threading.Lock()
        self.payload = None
        self.last = 0
        self.session = str(uuid.uuid4())
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path != '/snapshot':
                    self.send_error(404); return
                if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer '+owner.token):
                    self.send_error(401); return
                with owner.lock:
                    data = owner.payload if time.monotonic()-owner.last < 5 else None
                self.send_response(200 if data else 204)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                if data: self.wfile.write(data)
        self.server = ThreadingHTTPServer((os.getenv('BEAGLE_EXPORT_BIND', '127.0.0.1'), int(os.getenv('BEAGLE_EXPORT_PORT','8791'))), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def update(self, jpeg, seq, width, height, initialized, xyz=None):
        if not jpeg or time.monotonic()-self.last < .5: return
        frame_id = str(uuid.uuid4())
        context = {'producer':'beagle_eyes','odometry_initialized':bool(initialized)}
        if initialized and xyz is not None:
            context['latest_keyframe_pose'] = {'translation':[float(v) for v in xyz],
                'units':'arbitrary_monocular_scale','transform':'camera_to_world',
                'association':'latest_keyframe_not_necessarily_this_image'}
        metadata = {'schema_version':'firesight.frame.v1','frame_id':frame_id,'session_id':self.session,
            'source_sequence':int(seq),'received_at':datetime.now(timezone.utc).isoformat(),
            'timestamp_basis':'beagle_export_observation_time',
            'image':{'width':width,'height':height,'sha256':hashlib.sha256(jpeg).hexdigest()},'context':context}
        payload = json.dumps({'metadata':metadata,'jpeg_base64':base64.b64encode(jpeg).decode()},allow_nan=False).encode()
        with self.lock:
            self.payload=payload
            self.last=time.monotonic()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
