"""Run with sudo python3 cloud/test_receiver.py on the deployed VM.
Publishes two synthetic video bursts, verifies new JPEG/JSON pairs and reconnect.
No AI endpoint, external firewall change, or real drone required.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '-f', str(ROOT/'cloud/compose.yaml')]
BUNDLES = ROOT/'cloud/data/bundles'


def run(args, **kwargs):
    return subprocess.run(args, check=True, cwd=ROOT, **kwargs)


def ids():
    return {p.name for p in BUNDLES.glob('*') if not p.name.startswith('.') and (p/'metadata.json').exists()}


def main():
    run(COMPOSE + ['ps'])
    relay_id = subprocess.check_output(COMPOSE + ['ps', '-q', 'relay'], cwd=ROOT, text=True).strip()
    if not relay_id:
        raise SystemExit('Relay is not running')
    # Share the relay network namespace: no dependence on Compose project/network name.
    publisher = ['docker', 'run', '--rm', '--network', 'container:'+relay_id,
                 '--env-file', str(ROOT/'cloud/.env'), 'cloud-snapshots', 'sh', '-c',
                 'exec ffmpeg -hide_banner -loglevel error -re -f lavfi '
                 '-i testsrc2=size=640x360:rate=15 -t 12 -c:v libx264 '
                 '-preset ultrafast -tune zerolatency -g 15 -an -f flv '
                 '"rtmp://127.0.0.1:1935/live/dji?user=drone&pass=$PUBLISH_PASSWORD"']
    for attempt in (1, 2):
        before = ids()
        # Suppress FFmpeg errors which can include the credential-bearing URL.
        try:
            run(publisher, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=45)
        except subprocess.CalledProcessError:
            raise SystemExit('Test publisher failed; check relay availability/authentication privately')
        deadline = time.monotonic()+15
        new = ids()-before
        while not new and time.monotonic()<deadline:
            time.sleep(1)
            new = ids()-before
        if not new:
            raise SystemExit('FAIL: no new bundles. Check snapshots logs and available storage.')
        for frame_id in new:
            folder = BUNDLES/frame_id
            metadata = json.loads((folder/'metadata.json').read_text())
            jpeg = (folder/'frame.jpg').read_bytes()
            assert metadata['frame_id']==frame_id
            assert hashlib.sha256(jpeg).hexdigest()==metadata['image']['sha256']
            assert jpeg.startswith(b'\xff\xd8') and jpeg.endswith(b'\xff\xd9')
            # Decode with the same installed OpenCV runtime, no extra host packages.
            run(COMPOSE + ['exec', '-T', 'snapshots', 'python', '-c',
                'import cv2,sys; im=cv2.imread(sys.argv[1]); '
                'assert im is not None; assert im.shape[1]==int(sys.argv[2]); '
                'assert im.shape[0]==int(sys.argv[3])',
                '/data/bundles/'+frame_id+'/frame.jpg', str(metadata['image']['width']), str(metadata['image']['height'])], stdout=subprocess.DEVNULL)
        print(f'PASS burst {attempt}: {len(new)} new JPEG/JSON pairs, valid decode and checksums', flush=True)
        time.sleep(3)
    print('PASS: internal authenticated RTMP ingest, Beagle extraction, pairing, and reconnect.')
    print('Synthetic bundles remain on disk. External firewall and actual drone are not tested.')


if __name__=='__main__':
    main()
