"""Wearer GPS positions reported by the glasses app, and distance/bearing to mapped hazards."""
import math
import time

FRESH_S = 30          # a position older than this is no longer shown
MAX_WEARERS = 32      # bounded in-memory store for this single-process prototype
NEARBY_LIMIT = 3
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
INPUT_TYPES = {"click", "double_click", "scroll_up", "scroll_down", "long_press", "long_press_release"}
INPUT_SOURCES = {"right", "left", "ring", "unknown"}
MAX_IMU_SAMPLES = 120
MAX_INPUT_LOG = 20


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
    position.update(_validate_telemetry(data))
    return position


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_telemetry(data):
    """Optional glasses telemetry: device status, IMU samples [ms, x, y, z] and button presses."""
    out = {}
    device = data.get("device")
    if isinstance(device, dict):
        clean = {k: device[k] for k in ("worn", "charging", "in_case") if isinstance(device.get(k), bool)}
        if _number(device.get("battery")) and 0 <= device["battery"] <= 100:
            clean["battery"] = int(device["battery"])
        if isinstance(device.get("imu_on"), bool):
            clean["imu_on"] = device["imu_on"]
        if _number(device.get("imu_events")) and device["imu_events"] >= 0:
            clean["imu_events"] = int(device["imu_events"])
        out["device"] = clean
    imu = data.get("imu")
    if isinstance(imu, list):
        samples = [[float(v) for v in s] for s in imu[-MAX_IMU_SAMPLES:]
                   if isinstance(s, list) and len(s) == 4 and all(_number(v) for v in s)]
        if samples:
            out["imu"] = samples
    inputs = data.get("inputs")
    if isinstance(inputs, list):
        out["inputs"] = [{"type": i["type"], "source": i.get("source", "unknown"), "t": float(i["t"])}
                         for i in inputs[-MAX_INPUT_LOG:]
                         if isinstance(i, dict) and i.get("type") in INPUT_TYPES
                         and i.get("source", "unknown") in INPUT_SOURCES and _number(i.get("t"))]
    return out


def imu_stats(samples):
    """Per-axis mean and spread, sample rate and the latest reading, for the dashboard and tuning."""
    if not samples:
        return None
    axes = list(zip(*[s[1:] for s in samples]))
    mean = [sum(a) / len(a) for a in axes]
    spread = [math.sqrt(sum((v - m) ** 2 for v in a) / len(a)) for a, m in zip(axes, mean)]
    span_s = (samples[-1][0] - samples[0][0]) / 1000
    return {"n": len(samples), "rate_hz": round((len(samples) - 1) / span_s, 1) if span_s > 0 else None,
            "last": [round(v, 4) for v in samples[-1][1:]], "mean": [round(v, 4) for v in mean],
            "std": [round(v, 4) for v in spread], "samples": samples}


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


def _fmt(metres):
    return f"{round(metres / 10) * 10} m" if metres < 1000 else f"{metres / 1000:.1f} km"


def situation(nearby, trend_m=None):
    """A glasses alert built from the wearer's GPS and the nearest mapped hazard, or None.

    trend_m: how much nearer (positive) or farther (negative) the hazard is than ~10-20 s ago.
    """
    if not nearby:
        return None
    first = nearby[0]
    distance = first["distance_m"]
    approx = "~" if first.get("approx") else ""
    instructions = []
    if trend_m is not None:
        if trend_m >= 5:
            instructions.append(f"Closing in: {round(trend_m)} m nearer")
        elif trend_m <= -5:
            instructions.append(f"Moving away: {round(-trend_m)} m farther")
        else:
            instructions.append("Distance holding steady")
    instructions.append(f"Avoid heading {first['compass']}")
    for other in nearby[1:3]:
        instructions.append(f"Also {other['label']} {_fmt(other['distance_m'])} {other['compass']}")
    return {
        "priority": "critical" if distance < 100 else "warning" if distance < 300 else "info",
        "headline": f"{first['label']} {approx}{_fmt(distance)} {first['compass']}"[:40],
        "instructions": [line[:40] for line in instructions][:5],
    }


def map_key(position, nearby):
    """Changes when the wearer moves ~4 m or the nearby hazards change, so the glasses refetch the map."""
    grid = 0.00004
    cell = f"{round(position['lat'] / grid)}.{round(position['lon'] / grid)}"
    return cell + "-" + ".".join(f"{n['id']}{n['distance_m'] // 5}" for n in nearby)


class WearerStore:
    def __init__(self):
        self.positions = {}
        self.history = {}  # device_id -> [(ts, nearest distance m)], last ~30 s

    def trend(self, device_id, distance, now=None):
        """Record the nearest-hazard distance; return how much nearer it is than 10-20 s ago, if known."""
        now = time.time() if now is None else now
        samples = [(t, d) for t, d in self.history.get(device_id, []) if now - t <= 30]
        older = [d for t, d in samples if now - t >= 10]
        samples.append((now, distance))
        self.history[device_id] = samples
        return (older[-1] - distance) if older else None

    def update(self, position, now=None):
        now = time.time() if now is None else now
        device_id = position["device_id"]
        if device_id not in self.positions and len(self.positions) >= MAX_WEARERS:
            oldest = min(self.positions, key=lambda k: self.positions[k]["received_ts"])
            self.positions.pop(oldest)
        previous = self.positions.get(device_id, {})
        record = {**position, "received_ts": now}
        # Telemetry fields are kept until a newer report replaces them; presses accumulate.
        for key in ("device", "imu"):
            if key not in record and key in previous:
                record[key] = previous[key]
        record["inputs"] = (previous.get("inputs", []) + position.get("inputs", []))[-MAX_INPUT_LOG:]
        self.positions[device_id] = record
        return record

    def fresh(self, now=None):
        now = time.time() if now is None else now
        out = []
        for p in self.positions.values():
            if now - p["received_ts"] > FRESH_S:
                continue
            item = {k: v for k, v in p.items() if k not in ("received_ts", "imu")}
            item["age_s"] = round(now - p["received_ts"], 1)
            item["imu"] = imu_stats(p.get("imu"))
            out.append(item)
        return out
