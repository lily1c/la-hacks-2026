"""Consume completed Beagle bundles, newest first, without building an inference queue."""
import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import uuid


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timezone required')
    return parsed.timestamp()


class BundleWatcher:
    def __init__(self, directory, analyze, publish, lock, max_age=30):
        self.directory = Path(directory) if directory else None
        self.analyze, self.publish, self.lock = analyze, publish, lock
        self.max_age = max_age
        self.watermark = 0
        self.state = 'waiting_for_frames' if directory else 'not_configured'
        self.snapshot = None
        self.processed = 0
        self.errors = 0

    def newest(self):
        if not self.directory or not self.directory.is_dir():
            return None
        candidates = []
        for folder in self.directory.iterdir():
            try:
                if folder.is_symlink() or not folder.is_dir():
                    continue
                uuid.UUID(folder.name)  # Ignore atomic writer staging folders.
                meta_path = folder / 'metadata.json'
                if meta_path.stat().st_size > 65536:
                    continue
                meta = json.loads(meta_path.read_text())
                observed = timestamp(meta['received_at'])
                if meta['frame_id'] != folder.name or meta['schema_version'] != 'firesight.frame.v1':
                    continue
                if observed > self.watermark and 0 <= time.time() - observed <= self.max_age:
                    candidates.append((observed, folder, meta))
            except (OSError, ValueError, TypeError, KeyError):
                continue
        return max(candidates, key=lambda x: x[0]) if candidates else None

    async def tick(self):
        bundle = await asyncio.to_thread(self.newest)
        if not bundle:
            self.state = 'waiting_for_frames' if self.directory else 'not_configured'
            return
        observed, folder, metadata = bundle
        self.watermark = observed  # Attempt each frame once, including failed frames.
        path = folder / 'frame.jpg'
        if path.stat().st_size > 14 * 1024 * 1024:
            raise ValueError('Frame exceeds size limit')
        image = await asyncio.to_thread(path.read_bytes)
        if hashlib.sha256(image).hexdigest() != metadata['image']['sha256']:
            raise ValueError('Frame checksum mismatch')
        self.state = 'analyzing'
        async with self.lock:
            if time.time() - observed > self.max_age:
                return
            alert = await asyncio.to_thread(self.analyze, image, 'image/jpeg')
            if time.time() - observed > self.max_age:
                self.state = 'analysis_expired'
                return
            alert['id'] = metadata['frame_id']
            await self.publish(alert)
            self.snapshot = {'frame_id': metadata['frame_id'], 'metadata': metadata,
                             'alert': alert, 'image': 'data:image/jpeg;base64,' + base64.b64encode(image).decode()}
            self.processed += 1
            self.state = 'receiving'

    def status(self):
        fresh = bool(self.snapshot and time.time() - timestamp(self.snapshot['metadata']['received_at']) <= self.max_age)
        return {'state': self.state, 'configured': self.directory is not None,
                'fresh': fresh, 'processed': self.processed, 'errors': self.errors,
                'snapshot': self.snapshot if fresh else None}

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception as error:
                self.errors += 1
                self.state = 'analysis_error'
                print('Bundle analysis failed:', type(error).__name__, flush=True)
            await asyncio.sleep(0.5)


class RemoteBeagleWatcher(BundleWatcher):
    """Poll Greg's running exporter, retaining newest-only inference semantics."""
    def __init__(self, url, token, *args):
        super().__init__(None, *args)
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('BEAGLE_URL must be an HTTP(S) snapshot endpoint')
        self.url, self.token = url, token
        self.state = 'connecting_to_beagle'
        self.last_frame = None

    def fetch(self):
        from urllib.request import Request, build_opener, HTTPRedirectHandler
        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): return None
        request=Request(self.url,headers={'Authorization':'Bearer '+self.token})
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            if response.status==204: return None
            data=response.read(20*1024*1024+1)
        if len(data)>20*1024*1024: raise ValueError('Snapshot too large')
        return json.loads(data)

    async def tick(self):
        data=await asyncio.to_thread(self.fetch)
        if not data:
            self.state='waiting_for_beagle_frames'; return
        metadata=data['metadata'];identifier=metadata['frame_id'];uuid.UUID(identifier)
        if identifier==self.last_frame: return
        observed=timestamp(metadata['received_at'])
        if metadata['schema_version']!='firesight.frame.v1' or not 0<=time.time()-observed<=self.max_age:
            self.state='stale_beagle_frame'; return
        image=base64.b64decode(data['jpeg_base64'],validate=True)
        if len(image)>14*1024*1024 or hashlib.sha256(image).hexdigest()!=metadata['image']['sha256']:
            raise ValueError('Invalid image pair')
        self.last_frame=identifier
        self.state='analyzing'
        async with self.lock:
            alert=await asyncio.to_thread(self.analyze,image,'image/jpeg')
            if time.time()-observed>self.max_age:
                self.state='analysis_expired';return
            alert['id']=identifier
            await self.publish(alert)
            self.snapshot={'frame_id':identifier,'metadata':metadata,'alert':alert,
                'image':'data:image/jpeg;base64,'+data['jpeg_base64']}
            self.processed+=1
            self.state='receiving_from_beagle'

    def status(self):
        result=super().status()
        result['configured']=True
        result['source']='remote_beagle'
        return result
