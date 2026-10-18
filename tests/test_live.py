import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from firesight.live import BundleWatcher
from firesight.frame import analyze_frame

class LiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_continuous_bundles_checksum_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            results=[]
            async def publish(alert): results.append(alert)
            watcher=BundleWatcher(directory,analyze_frame,publish,asyncio.Lock())
            image=Path('wildfire.jpeg').read_bytes()
            def save(offset=0, corrupt=False):
                identifier=str(uuid.uuid4());p=Path(directory)/identifier;p.mkdir()
                (p/'frame.jpg').write_bytes(image)
                record={'schema_version':'firesight.frame.v1','frame_id':identifier,'received_at':(datetime.now(timezone.utc)+timedelta(seconds=offset)).isoformat(),'image':{'sha256':'bad' if corrupt else hashlib.sha256(image).hexdigest()}}
                (p/'metadata.json').write_text(json.dumps(record));return identifier
            save(-60)
            first=save()
            await watcher.tick()
            self.assertEqual(results[-1]['id'],first)
            self.assertEqual(watcher.status()['snapshot']['metadata']['frame_id'],first)
            await watcher.tick()
            self.assertEqual(len(results),1)
            second=save()
            await watcher.tick()
            self.assertEqual(results[-1]['id'],second)
            save(corrupt=True)
            with self.assertRaises(ValueError): await watcher.tick()
            self.assertEqual(len(results),2)
            watcher.snapshot['metadata']['received_at']='2020-01-01T00:00:00Z'
            self.assertIsNone(watcher.status()['snapshot'])

    async def test_remote_beagle_watcher_with_broadcaster(self):
        import sys
        import numpy as np
        beagle_root = Path(__file__).resolve().parent.parent / 'vendor' / 'beagle_eyes'
        if str(beagle_root) not in sys.path:
            sys.path.insert(0, str(beagle_root))
        from broadcast.broadcaster import TelemetryBroadcaster
        from firesight.live import RemoteBeagleWatcher

        broadcaster = TelemetryBroadcaster(host='127.0.0.1', port=18765).start()
        try:
            results = []
            async def publish(alert):
                results.append(alert)
            watcher = RemoteBeagleWatcher(
                'http://127.0.0.1:18765/snapshot',
                '',
                analyze_frame,
                publish,
                asyncio.Lock(),
            )
            # Before any real frame, /snapshot returns 204
            await watcher.tick()
            self.assertEqual(watcher.state, 'waiting_for_beagle_frames')
            self.assertEqual(len(results), 0)

            # Publish a real frame and telemetry
            frame_bgr = np.zeros((360, 640, 3), dtype=np.uint8)
            broadcaster.publish_frame(frame_bgr=frame_bgr)
            broadcaster.publish_telemetry(
                pose=[1.25, -0.5, 3.75, 0.0, 0.0, 0.0, 1.0],
                frame_id=42,
                fps=30.0,
                vo_hz=15.0,
                infer_ms=8.2,
                initialized=True,
                extra={'detections_3d': [{'id': 1, 'label': 'person', 'distance_m': 2.8, 'center': [0.5, 0.0, 2.8], 'size': [0.6, 1.7, 0.6]}]},
            )

            await watcher.tick()
            status = watcher.status()
            self.assertTrue(status['fresh'])
            self.assertEqual(status['beagle_host'], '127.0.0.1:18765')
            self.assertEqual(status['beagle_ws_url'], 'ws://127.0.0.1:18765/ws')
            self.assertEqual(len(results), 1)
            telem = status['snapshot']['metadata']['telemetry']
            self.assertEqual(telem['pose']['position'], [1.25, -0.5, 3.75])
            self.assertEqual(telem['detections_3d'][0]['distance_m'], 2.8)
        finally:
            broadcaster.stop()

if __name__=='__main__': unittest.main()
