import asyncio
import base64
import math
import time
import unittest

from firesight.analysis.annotator import build_annotations
from firesight.services.annotations import AnnotationService
from firesight.services.geoproject import enu_to_latlon, pixel_to_ground

ORIGIN = {"lat": 34.070233, "lon": -118.445185, "source": "fixed"}


def camera(height=10.0, pitch_deg=45.0):
    """Camera facing east, pitched down; axes rows are right, down, forward in ENU."""
    p = math.radians(pitch_deg)
    forward = [math.cos(p), 0.0, -math.sin(p)]
    down = [-math.sin(p), 0.0, -math.cos(p)]
    right = [0.0, -1.0, 0.0]
    return {"enu": [0.0, 0.0, height], "axes_enu": [right, down, forward],
            "intrinsics": [500.0, 500.0, 320.0, 180.0], "image_size": [640, 360]}


class GroundProjectionTests(unittest.TestCase):
    def test_center_pixel_hits_ground_ahead(self):
        enu, clamped = pixel_to_ground(camera(10, 45), 320, 180)
        self.assertFalse(clamped)
        self.assertAlmostEqual(enu[0], 10.0, places=3)  # 45 deg down from 10 m -> 10 m east
        self.assertAlmostEqual(enu[1], 0.0, places=3)

    def test_right_of_image_is_south_when_facing_east(self):
        enu, _ = pixel_to_ground(camera(10, 90 - 1e-3), 820, 180)
        self.assertLess(enu[1], 0)

    def test_sky_ray_is_clamped(self):
        enu, clamped = pixel_to_ground(camera(10, 0.0), 320, 0)
        self.assertTrue(clamped)
        self.assertAlmostEqual(math.hypot(enu[0], enu[1]), 150.0, places=3)

    def test_enu_to_latlon_scale(self):
        lat, lon = enu_to_latlon([100.0, 100.0], ORIGIN)
        self.assertAlmostEqual((lat - ORIGIN["lat"]) * 111_000, 100.0, delta=1.0)
        self.assertAlmostEqual((lon - ORIGIN["lon"]) * 111_320 * math.cos(math.radians(ORIGIN["lat"])), 100.0, delta=1.0)


class BuildAnnotationTests(unittest.TestCase):
    geo = {"camera": camera(), "origin": ORIGIN, "transform_v_to_e": {"calibrated": True}}

    def test_area_becomes_polygon_and_vehicle_becomes_point(self):
        items = [{"label": "Crash", "kind": "incident", "severity": "critical", "box_2d": [500, 400, 800, 600]},
                 {"label": "Car", "kind": "vehicle", "severity": "info", "box_2d": [500, 400, 800, 600]},
                 {"label": "bad", "kind": "vehicle"}]
        out = build_annotations(items, self.geo, "f1", 1000.0)
        self.assertEqual([a["geometry"]["type"] for a in out], ["Polygon", "Point"])
        self.assertEqual(len(out[0]["geometry"]["latlon"]), 4)
        self.assertFalse(out[0]["approx"])

    def test_no_camera_leaves_annotation_unplaced_and_unknown_kind_is_other(self):
        out = build_annotations([{"label": "x", "kind": "weird", "severity": "bad", "box_2d": [0, 0, 10, 10]}], {}, "f", 1.0)
        self.assertIsNone(out[0]["geometry"])
        self.assertEqual((out[0]["kind"], out[0]["severity"], out[0]["approx"]), ("other", "info", True))


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    def snapshot(self, age=0):
        telemetry = {"timestamp": time.time() - age, "geo": BuildAnnotationTests.geo}
        return {"frame_id": "f1", "image": "data:image/jpeg;base64," + base64.b64encode(b"jpg").decode(),
                "metadata": {"telemetry": telemetry}}

    async def test_run_once_uses_prompt_and_stores_annotations(self):
        seen = []

        def detect(image, prompt, geo):
            seen.append((image, prompt))
            return [{"label": "Crash", "kind": "incident", "severity": "warning", "box_2d": [400, 400, 700, 700]}]

        service = AnnotationService(lambda: self.snapshot(), detect)
        self.assertIn("first", (await service.run_once())["error"])
        service.configure(prompt="  mark car crashes  ")
        state = await service.run_once()
        self.assertEqual(seen, [(b"jpg", "mark car crashes")])
        self.assertEqual(len(state["annotations"]), 1)
        self.assertIsNone(state["error"])
        service.configure(prompt="mark trees")  # new question clears old answers
        self.assertEqual(service.state()["annotations"], [])

    async def test_stale_frame_and_detector_errors_are_reported(self):
        service = AnnotationService(lambda: self.snapshot(age=120), lambda *a: [])
        service.configure(prompt="x")
        self.assertIn("stale", (await service.run_once())["error"])
        from firesight.analysis.gemini import GeminiConfigurationError

        def boom(*a): raise GeminiConfigurationError("Set GEMINI_API_KEY")
        service = AnnotationService(lambda: self.snapshot(), boom)
        service.configure(prompt="x")
        self.assertIn("GEMINI_API_KEY", (await service.run_once())["error"])
        self.assertFalse(service.busy)

    async def test_auto_loop_annotates_each_frame_once(self):
        calls = []
        service = AnnotationService(lambda: self.snapshot(), lambda *a: calls.append(1) or [])
        service.configure(prompt="x", auto=True, interval_s=1)
        task = asyncio.create_task(service.run())
        await asyncio.sleep(0.8)
        task.cancel()
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
