"""Bounded, latest-only ingestion of explicitly paired Beagle frames."""
import asyncio
import base64
import hashlib
import math
import time
import uuid
from datetime import datetime, timezone

from firesight.live import BundleWatcher


class PushReceiver(BundleWatcher):
    def __init__(self, *args):
        super().__init__(None, *args)
        self.pending = None
        self.sequence = {}
        self.state = 'waiting_for_sender'

    def accept(self, data):
        session = str(uuid.UUID(data['session_id']))
        telemetry = data['telemetry']
        if not isinstance(telemetry, dict):
            raise ValueError('telemetry must be an object')
        pose = telemetry.get('pose') or {}
        if not isinstance(pose, dict):
            raise ValueError('pose must be an object')
        position = pose.get('position')
        if position is not None and (not isinstance(position, list) or len(position) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in position)):
            raise ValueError('pose.position must contain three finite numbers')
        number = telemetry['frame_id']
        if type(number) is not int or number < 0:
            raise ValueError('telemetry.frame_id must be a nonnegative integer')
        observed = telemetry['timestamp']
        if not isinstance(observed, (int, float)) or not 0 <= time.time() - observed <= self.max_age:
            raise ValueError('Telemetry timestamp must be fresh Unix seconds')
        image = base64.b64decode(data['jpeg_base64'], validate=True)
        if not image or len(image) > 8 * 1024 * 1024:
            raise ValueError('JPEG must be between 1 byte and 8 MiB')
        if hashlib.sha256(image).hexdigest() != data['sha256']:
            raise ValueError('JPEG checksum mismatch')
        identifier = str(uuid.uuid5(uuid.UUID(session), str(number)))
        if number <= self.sequence.get(session, -1):
            return {'frame_id': identifier, 'accepted': False, 'reason': 'duplicate_or_out_of_order'}
        # Bound session tracking; one session UUID per sender process.
        if session not in self.sequence and len(self.sequence) >= 128:
            self.sequence.pop(next(iter(self.sequence)))
        self.sequence[session] = number
        metadata = {'schema_version': 'firesight.frame.v1', 'frame_id': identifier,
                    'session_id': session, 'source_frame_id': number,
                    'received_at': datetime.fromtimestamp(observed, timezone.utc).isoformat(),
                    'image': {'sha256': data['sha256']}, 'telemetry': telemetry,
                    'context': {'latest_keyframe_pose': {'translation': position}}}
        self.pending = (image, metadata)
        self.state = 'receiving'
        self.snapshot = {'frame_id': identifier, 'metadata': metadata, 'alert': None,
                         'image': 'data:image/jpeg;base64,' + data['jpeg_base64']}
        return {'frame_id': identifier, 'accepted': True}

    async def tick(self):
        if self.pending is None:
            return
        image, metadata = self.pending
        self.pending = None
        async with self.lock:
            from firesight.live import timestamp
            if time.time() - timestamp(metadata['received_at']) > self.max_age:
                return
            alert = await asyncio.to_thread(self.analyze, image, 'image/jpeg')
            if time.time() - timestamp(metadata['received_at']) > self.max_age:
                return
            alert['id'] = metadata['frame_id']
            await self.publish(alert)
            if self.snapshot['frame_id'] == metadata['frame_id']:
                self.snapshot['alert'] = alert
            self.processed += 1

    def status(self):
        result = super().status()
        result.update(configured=True, source='beagle_push')
        return result
