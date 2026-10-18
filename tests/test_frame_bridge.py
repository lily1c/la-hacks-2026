import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / 'integrations/beagle_eyes/frame_bridge.py'
spec = importlib.util.spec_from_file_location('frame_bridge', path)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class FrameBridgeTests(unittest.TestCase):
    def test_full_queue_preserves_pending_and_skips_new_frames(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = bridge.FrameBridge(directory)
            writer.max_bundles = 1
            first = writer.save_jpeg(b'\xff\xd8test\xff\xd9', 1, 1, 1)
            self.assertIsNone(writer.save_jpeg(b'\xff\xd8test\xff\xd9', 1, 1, 2))
            self.assertEqual([p.name for p in bridge.bundles(directory)], [first['frame_id']])

    def test_atomic_pair_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = bridge.FrameBridge(directory)
            image = b'\xff\xd8test-payload\xff\xd9'
            first = writer.save_jpeg(image, 640, 360, 42, {'producer': 'beagle_eyes'})
            second = writer.save_jpeg(image, 640, 360, 42)
            self.assertNotEqual(first['frame_id'], second['frame_id'])
            self.assertEqual(first['session_id'], second['session_id'])
            self.assertEqual(len(bridge.bundles(directory)), 2)
            folder = Path(directory) / first['frame_id']
            metadata = json.loads((folder / 'metadata.json').read_text())
            self.assertEqual(metadata['image']['sha256'], hashlib.sha256((folder / 'frame.jpg').read_bytes()).hexdigest())
            self.assertEqual(metadata['source_sequence'], 42)
            (Path(directory) / '.incomplete').mkdir()
            self.assertEqual(len(bridge.bundles(directory)), 2)

    def test_failure_is_retained_and_success_marks_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            record = bridge.FrameBridge(directory).save_jpeg(b'\xff\xd8test\xff\xd9', 1, 1, 1)
            folder = Path(directory) / record['frame_id']
            with patch('urllib.request.build_opener') as build:
                build.return_value.open.side_effect = TimeoutError
                with self.assertRaises(TimeoutError):
                    bridge.deliver(folder, 'https://ai.example/frames')
                self.assertFalse((folder / 'delivered').exists())
            with patch('urllib.request.build_opener') as build:
                build.return_value.open.return_value.__enter__.return_value.status = 202
                bridge.deliver(folder, 'https://ai.example/frames', 'test-token')
                request = build.return_value.open.call_args.args[0]
                self.assertEqual(request.get_header('Idempotency-key'), record['frame_id'])
                self.assertIn(b'name="image"', request.data)
                self.assertIn(record['frame_id'].encode(), request.data)
                self.assertTrue((folder / 'delivered').exists())

    def test_rejects_corrupted_image_and_nonfinite_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            writer = bridge.FrameBridge(directory)
            with self.assertRaises(ValueError):
                writer.save_jpeg(b'not-jpeg', 1, 1, 1)
            with self.assertRaises(ValueError):
                writer.save_jpeg(b'\xff\xd8test\xff\xd9', 1, 1, 1, {'x': float('nan')})
            self.assertEqual(bridge.bundles(directory), [])
            record = writer.save_jpeg(b'\xff\xd8test\xff\xd9', 1, 1, 1)
            folder = Path(directory) / record['frame_id']
            (folder / 'frame.jpg').write_bytes(b'corrupted')
            with self.assertRaises(ValueError):
                bridge.deliver(folder, 'https://ai.example/frames')


if __name__ == '__main__':
    unittest.main()
