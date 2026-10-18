import asyncio
import base64
import hashlib
import time
import unittest
import uuid
from firesight.push import PushReceiver

class PushTests(unittest.IsolatedAsyncioTestCase):
    async def test_identity_latest_only_and_retries(self):
        published=[]
        async def publish(alert): published.append(alert)
        receiver=PushReceiver(lambda image, kind: {'id':'old'}, publish, asyncio.Lock())
        image=b'jpeg-test'
        packet={'session_id':str(uuid.uuid4()), 'telemetry':{'frame_id':1,'timestamp':time.time(),'pose':{'position':[1,2,3]}},'jpeg_base64':base64.b64encode(image).decode(),'sha256':hashlib.sha256(image).hexdigest()}
        first=receiver.accept(packet)
        self.assertFalse(receiver.accept(packet)['accepted'])
        packet['telemetry']=dict(packet['telemetry'],frame_id=2)
        second=receiver.accept(packet)
        self.assertNotEqual(first['frame_id'],second['frame_id'])
        self.assertEqual(receiver.status()['snapshot']['metadata']['telemetry']['pose']['position'],[1,2,3])
        await receiver.tick()
        self.assertEqual(published,[{'id':second['frame_id']}])
        packet['sha256']='wrong'
        with self.assertRaises(ValueError): receiver.accept(packet)
        packet['telemetry']['timestamp']=time.time()-60
        with self.assertRaises(ValueError): receiver.accept(packet)
