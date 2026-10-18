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

if __name__=='__main__': unittest.main()
