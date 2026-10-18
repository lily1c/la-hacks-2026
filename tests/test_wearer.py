"""Wearer GPS reports from the glasses phone and distance/bearing to mapped hazards."""
import os
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from firesight.api import app, wearers
from firesight.services.wearer import WearerStore, bearing_deg, distance_m, nearby_hazards, situation, validate_position

HERE = [34.0722, -118.4452]  # UCLA


def hazard(label, latlon, kind="incident"):
    return {"id": label, "label": label, "kind": kind, "severity": "critical", "approx": True,
            "geometry": {"type": "Point", "latlon": [latlon]}}


class GeometryTests(unittest.TestCase):
    def test_distance_and_bearing(self):
        north = [HERE[0] + 0.001, HERE[1]]  # ~111 m north
        self.assertAlmostEqual(distance_m(HERE, north), 111, delta=1)
        self.assertAlmostEqual(bearing_deg(HERE, north), 0, delta=0.5)
        east = [HERE[0], HERE[1] + 0.001]
        self.assertAlmostEqual(bearing_deg(HERE, east), 90, delta=0.5)

    def test_nearby_sorted_with_compass(self):
        position = {"lat": HERE[0], "lon": HERE[1]}
        items = [hazard("far", [HERE[0] + 0.01, HERE[1]]),
                 hazard("near", [HERE[0] + 0.001, HERE[1] + 0.001]),
                 {"id": "unplaced", "label": "unplaced", "geometry": None}]
        result = nearby_hazards(position, items)
        self.assertEqual([r["label"] for r in result], ["near", "far"])
        self.assertEqual(result[0]["compass"], "NE")

    def test_validation(self):
        self.assertEqual(validate_position({"lat": 1, "lon": 2, "accuracy_m": 5})["accuracy_m"], 5.0)
        for bad in [{"lat": 91, "lon": 0}, {"lat": 0}, {"lat": "1", "lon": 2}, []]:
            with self.assertRaises(ValueError):
                validate_position(bad)

    def test_store_freshness(self):
        store = WearerStore()
        store.update({"device_id": "a", "lat": 1.0, "lon": 2.0}, now=100)
        self.assertEqual(len(store.fresh(now=110)), 1)
        self.assertEqual(store.fresh(now=200), [])


class SituationTests(unittest.TestCase):
    def test_alert_from_nearest_hazard(self):
        near = [{"id": "a", "label": "Fire front", "distance_m": 85, "compass": "NE", "approx": True}]
        alert = situation(near, trend_m=12)
        self.assertEqual(alert["priority"], "critical")
        self.assertEqual(alert["headline"], "Fire front ~80 m NE")
        self.assertEqual(alert["instructions"][:2], ["Closing in: 12 m nearer", "Avoid heading NE"])
        self.assertIsNone(situation([]))

    def test_trend_compares_with_10_to_20_seconds_ago(self):
        store = WearerStore()
        self.assertIsNone(store.trend("g2", 200, now=100))
        self.assertIsNone(store.trend("g2", 195, now=105))
        self.assertEqual(store.trend("g2", 180, now=112), 20)


class WearerApiTests(unittest.TestCase):
    def test_report_and_read_position(self):
        wearers.positions.clear()
        body = {"lat": HERE[0], "lon": HERE[1], "accuracy_m": 8}
        with patch.dict(os.environ, {"G2_REPORT_TOKEN": "phone-test", "FIRESIGHT_DETECTOR": "opencv"}):
            with TestClient(app) as client:
                self.assertEqual(client.post("/wearer", json=body).status_code, 401)
                self.assertEqual(client.post("/wearer", json={"lat": 200}, headers={"Authorization": "Bearer phone-test"}).status_code, 422)
                app.state.annotations.annotations = [
                    {**hazard("Fire front", [HERE[0] + 0.001, HERE[1]]), "ts": time.time(), "ttl_s": 60}]
                response = client.post("/wearer", json=body, headers={"Authorization": "Bearer phone-test"})
                self.assertEqual(response.status_code, 200, response.text)
                nearest = response.json()["nearby"][0]
                self.assertEqual((nearest["label"], nearest["compass"]), ("Fire front", "N"))
                self.assertAlmostEqual(nearest["distance_m"], 111, delta=1)
                reply = response.json()
                self.assertEqual(reply["situation"]["headline"], "Fire front ~110 m N")
                image = client.get(reply["map_url"])
                self.assertEqual(image.headers["content-type"], "image/png")
                self.assertEqual(client.get("/wearer/map.png?device=nobody").status_code, 404)
                listed = client.get("/wearer").json()
                self.assertTrue(listed["configured"])
                self.assertEqual(listed["wearers"][0]["accuracy_m"], 8.0)
        with patch.dict(os.environ, {"G2_REPORT_TOKEN": ""}):
            with TestClient(app) as client:
                self.assertEqual(client.post("/wearer", json=body).status_code, 503)


if __name__ == "__main__":
    unittest.main()
