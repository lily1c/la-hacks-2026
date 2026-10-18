"""Opt-in demo: one fake fire placed near the first glasses wearer, for showing GPS features without a drone.

Enabled with FIRESIGHT_DEMO_HAZARD=true. The fire is placed FIRESIGHT_DEMO_HAZARD_M metres (default 180)
north-east of the first wearer position the backend receives and then stays put, so walking changes the
distance. It is labelled "Demo fire". Real Gemini annotations replace it whenever they exist.
"""
import asyncio
import math
import os
import time

SIZE_M = 25
BEARING_DEG = 45


def _offset(lat, lon, distance, bearing):
    rad = math.radians(bearing)
    return (lat + distance * math.cos(rad) / 111320,
            lon + distance * math.sin(rad) / (111320 * math.cos(math.radians(lat))))


def enabled():
    return os.getenv("FIRESIGHT_DEMO_HAZARD") == "true"


async def run_demo_hazard(annotations, wearers):
    distance = float(os.getenv("FIRESIGHT_DEMO_HAZARD_M", "180"))
    corners = None
    while True:
        first = min(wearers.positions.values(), key=lambda p: p["received_ts"], default=None)
        if first and corners is None:
            lat, lon = _offset(first["lat"], first["lon"], distance, BEARING_DEG)
            corners = [_offset(lat, lon, SIZE_M, b) for b in (0, 90, 180, 270)]
        real = [a for a in annotations.annotations if a.get("id") != "demo-fire"]
        if corners and not real:
            annotations.annotations = [{
                "id": "demo-fire", "source": "demo", "kind": "incident", "label": "Demo fire",
                "severity": "critical", "approx": True, "ts": time.time(), "ttl_s": 60,
                "summary": "Demo hazard for showing GPS features (FIRESIGHT_DEMO_HAZARD)",
                "geometry": {"type": "Polygon", "latlon": [[round(a, 7), round(b, 7)] for a, b in corners]}}]
        await asyncio.sleep(5)
