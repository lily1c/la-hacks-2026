"""Real local MediaMTX → Beagle JPEG → multipart HTTP test. Requires ffmpeg."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from email.parser import BytesParser
from email.policy import default
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'integrations/beagle_eyes'))
from frame_bridge import bundles, deliver
received = []
class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        parts = BytesParser(policy=default).parsebytes(
            ('Content-Type: '+self.headers['Content-Type']+'\r\n\r\n').encode()+body)
        fields = {p.get_param('name', header='content-disposition'):p.get_payload(decode=True) for p in parts.iter_parts()}
        metadata = json.loads(fields['metadata'])
        assert metadata['image']['sha256'] == hashlib.sha256(fields['image']).hexdigest()
        assert self.headers['Idempotency-Key'] == metadata['frame_id']
        received.append(metadata)
        self.send_response(202); self.end_headers()
    def log_message(self,*args): pass

def main():
    processes=[]
    server=HTTPServer(('127.0.0.1',0),Receiver)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp)
        config=tmp/'mediamtx.yml'
        config.write_text('''logLevel: info
rtmpAddress: 127.0.0.1:21935
rtsp: false
hls: false
webrtc: false
srt: false
moq: false
authInternalUsers:
- user: drone
  pass: test-publish
  permissions: [{action: publish, path: live/dji}]
- user: reader
  pass: test-read
  permissions: [{action: read, path: live/dji}]
paths:
  live/dji:
''')
        try:
            processes.append(subprocess.Popen([str(ROOT/'.runtime/mediamtx'),str(config)]))
            time.sleep(1)
            processes.append(subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-re','-f','lavfi','-i','testsrc2=size=640x360:rate=15','-c:v','libx264','-preset','ultrafast','-tune','zerolatency','-g','15','-an','-f','flv','rtmp://127.0.0.1:21935/live/dji?user=drone&pass=test-publish'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            subprocess.run([sys.executable,str(ROOT/'scripts/beagle_capture.py'),'--source','rtmp://127.0.0.1:21935/live/dji?user=reader&pass=test-read','--directory',str(tmp/'bundles'),'--max-frames','3'],check=True,timeout=40)
            folders=bundles(tmp/'bundles')
            assert len(folders)==3
            for folder in folders:
                deliver(folder,f'http://127.0.0.1:{server.server_port}/frame')
                assert (folder/'delivered').exists()
            assert len(received)==3
            print('PASS: authenticated RTMP → Beagle reader → 3 matching JPEG/JSON pairs → HTTP acknowledgments')
        finally:
            for proc in reversed(processes):
                proc.terminate()
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired: proc.kill();proc.wait()
            server.shutdown();server.server_close()
if __name__=='__main__': main()
