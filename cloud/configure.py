"""Run once ON THE VM before compose up. Never commit generated secrets."""
import json
import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parent
env = root / '.env'
config = root / 'mediamtx.generated.yml'
if env.exists() or config.exists():
    raise SystemExit('Configuration exists; refusing to rotate or overwrite credentials.')
publisher = secrets.token_hex(24)
reader = secrets.token_hex(24)
os.umask(0o077)
env.write_text(f'PUBLISH_PASSWORD={publisher}\nREAD_PASSWORD={reader}\nAI_ENDPOINT=\nAI_TOKEN=\n')
users = [
    {'user': 'drone', 'pass': publisher, 'permissions': [{'action': 'publish', 'path': 'live/dji'}]},
    {'user': 'reader', 'pass': reader, 'permissions': [{'action': 'read', 'path': 'live/dji'}]},
]
config.write_text('''logLevel: warn
api: false
rtmp: true
rtmpAddress: :1935
rtsp: true
rtspAddress: :8554
rtspTransports: [tcp]
hls: false
webrtc: false
srt: false
moq: false
authMethod: internal
authInternalUsers: ''' + json.dumps(users) + '''
paths:
  live/dji:
    source: publisher
    overridePublisher: false
''')
data = root / 'data'
data.mkdir(exist_ok=True)
# Match the unprivileged worker inside the Linux container.
if os.geteuid() == 0:
    os.chown(data, 10001, 10001)
else:
    print('On the VM, run: sudo chown 10001:10001 cloud/data')
print('Generated private configuration. Credentials are in cloud/.env; keep this file private.')
