"""Wearer GPS positions reported by the glasses app, and distance/bearing to mapped hazards."""
import math
import time

FRESH_S = 30          # a position older than this is no longer shown
MAX_WEARERS = 32      # bounded in-memory store for this single-process prototype
NEARBY_LIMIT = 3
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def validate_position(data):
    """Normalize a POST /wearer payload. Raises ValueError on bad input."""
    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")
    lat, lon = data.get("lat"), data.get("lon")
    if not isinstance(lat, (int, float)) or not -90 <= lat <= 90:
        raise ValueError("lat must be a number between -90 and 90")
    if not isinstance(lon, (int, float)) or not -180 <= lon <= 180:
        raise ValueError("lon must be a number between -180 and 180")
    device = data.get("device_id", "g2")
    if not isinstance(device, str) or not 1 <= len(device) <= 64:
        raise ValueError("device_id must be a string of 1 to 64 characters")
    position = {"device_id": device, "lat": float(lat), "lon": float(lon)}
    for key in ("accuracy_m", "heading_deg", "speed_mps"):
        value = data.get(key)
        if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            position[key] = round(float(value), 1)
    return position


def distance_m(a, b):
    """Great-circle distance in metres between [lat, lon] points."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def bearing_deg(a, b):
    """Initial compass bearing from a to b, 0 = north, clockwise."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def nearby_hazards(position, annotations, limit=NEARBY_LIMIT):
    """Mapped annotations sorted by distance from the wearer, with compass direction."""
    here = [position["lat"], position["lon"]]
    results = []
    for item in annotations or []:
        points = ((item.get("geometry") or {}).get("latlon")) or []
        if not points:
            continue
        nearest = min(points, key=lambda p: distance_m(here, p))
        distance = distance_m(here, nearest)
        bearing = bearing_deg(here, nearest)
        results.append({
            "id": item.get("id"), "label": item.get("label") or item.get("kind") or "hazard",
            "kind": item.get("kind"), "severity": item.get("severity", "info"),
            "distance_m": round(distance), "bearing_deg": round(bearing),
            "compass": COMPASS[round(bearing / 45) % 8], "approx": bool(item.get("approx")),
        })
    results.sort(key=lambda r: r["distance_m"])
    return results[:limit]


class WearerStore:
    def __init__(self):
        self.positions = {}

    def update(self, position, now=None):
        now = time.time() if now is None else now
        if position["device_id"] not in self.positions and len(self.positions) >= MAX_WEARERS:
            oldest = min(self.positions, key=lambda k: self.positions[k]["received_ts"])
            self.positions.pop(oldest)
        record = {**position, "received_ts": now}
        self.positions[position["device_id"]] = record
        return record

    def fresh(self, now=None):
        now = time.time() if now is None else now
        return [
            {**{k: v for k, v in p.items() if k != "received_ts"}, "age_s": round(now - p["received_ts"], 1)}
            for p in self.positions.values() if now - p["received_ts"] <= FRESH_S
        ]
