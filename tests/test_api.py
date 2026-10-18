"""Exercise real HTTP contracts across receiver, analysis and glasses reports."""
import base64
import hashlib
import os
from pathlib import Path
import time
import unittest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from firesight.api import app

class ApiTests(unittest.TestCase):
    def test_push_to_alert_and_glasses(self):
        image=Path('wildfire.jpeg').read_bytes()
        payload={'session_id':str(uuid.uuid4()), 'telemetry':{'frame_id':1,'timestamp':time.time(),'pose':{'position':[1,2,3]}}, 'jpeg_base64':base64.b64encode(image).decode(),'sha256':hashlib.sha256(image).hexdigest()}
        headers={'Authorization':'Bearer ingest-test'}
        with patch.dict(os.environ, {'INGEST_MODE':'push','INGEST_TOKEN':'ingest-test','PUBLIC_DEPLOYMENT':'true','FIRESIGHT_DETECTOR':'opencv','G2_REPORT_TOKEN':'display-test','FIRESIGHT_DEMO_MAP':'true'}):
            with TestClient(app) as client:
                self.assertEqual(client.get('/health').status_code,200)
                for path in ['/', '/assets/app.js','/assets/styles.css']:
                    self.assertEqual(client.get(path).status_code,200)
                self.assertEqual(client.post('/ingest/beagle',json=payload).status_code,401)
                response=client.post('/ingest/beagle',json=payload,headers=headers)
                self.assertEqual(response.status_code,202,response.text)
                identifier=response.json()['frame_id']
                live=client.get('/live').json()
                self.assertEqual(live['snapshot']['metadata']['telemetry'],payload['telemetry'])
                client.portal.call(app.state.watcher.tick)
                alert=client.get('/latest').json()
                self.assertEqual(alert['id'],identifier)
                self.assertIn('map_url',alert)
                self.assertEqual(client.get(alert['map_url']).headers['content-type'],'image/png')
                self.assertEqual(client.post('/ingest/beagle',json=payload,headers=headers).json()['accepted'],False)
                payload['telemetry']['frame_id']=2
                self.assertEqual(client.post('/ingest/beagle',json=payload,headers=headers).status_code,202)
                report={'alert_id':identifier,'rendered_text':alert['headline'],'status':'sdk_accepted'}
                self.assertEqual(client.post('/g2/display',json=report).status_code,401)
                self.assertEqual(client.post('/g2/display',json=report,headers={'Authorization':'Bearer display-test'}).status_code,200)
                self.assertEqual(client.get('/g2/status').json()['report']['alert_id'],identifier)
                payload['sha256']='bad'
                self.assertEqual(client.post('/ingest/beagle',json=payload,headers=headers).status_code,422)
                app.state.watcher.snapshot['metadata']['received_at']='2000-01-01T00:00:00Z'
                self.assertFalse(client.get('/live').json()['fresh'])

    def test_legacy_frame_and_demo_disabled(self):
        with patch.dict(os.environ, {'INGEST_MODE':'push','FIRESIGHT_DETECTOR':'opencv','PUBLIC_DEPLOYMENT':'false','FIRESIGHT_DEMO_MAP':'false'}):
            with TestClient(app) as client:
                response=client.post('/frame',content=Path('wildfire.jpeg').read_bytes(),headers={'Content-Type':'image/jpeg'})
                self.assertEqual(response.status_code,200,response.text)
                self.assertNotIn('map_url',client.get('/latest').json())
                self.assertEqual(client.get('/view.png').status_code,404)
