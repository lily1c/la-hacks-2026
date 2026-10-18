"""288x144 greyscale map for the G2 glasses, drawn from the wearer's GPS and mapped annotations.

North is up and the wearer is at the centre. The scale zooms to fit the nearest hazard.
Black is transparent on the glasses; bright values are lit.
"""
import math

import cv2
import numpy as np

W, H = 288, 144
CX, CY = W // 2, H // 2
NICE_RANGES = [50, 75, 100, 150, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000]  # metres from centre to the top edge


def _range_for(nearest_m):
    want = nearest_m * 1.25 if nearest_m else 200
    return next((r for r in NICE_RANGES if r >= want), NICE_RANGES[-1])


def _to_px(lat, lon, origin, metres_per_px):
    east = (lon - origin[1]) * 111320 * math.cos(math.radians(origin[0]))
    north = (lat - origin[0]) * 111320
    return CX + east / metres_per_px, CY - north / metres_per_px


def _label(img, text, x, y, value=200):
    cv2.putText(img, text, (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, value, 1, cv2.LINE_AA)


def _edge_arrow(img, x, y, distance_m):
    """Hazard is off the map: draw an arrow on the border pointing at it, with its distance."""
    angle = math.atan2(y - CY, x - CX)
    reach = min((CX - 10) / max(abs(math.cos(angle)), 1e-6), (CY - 10) / max(abs(math.sin(angle)), 1e-6))
    tip = (CX + reach * math.cos(angle), CY + reach * math.sin(angle))
    back = 12
    left = (tip[0] - back * math.cos(angle - 0.5), tip[1] - back * math.sin(angle - 0.5))
    right = (tip[0] - back * math.cos(angle + 0.5), tip[1] - back * math.sin(angle + 0.5))
    cv2.fillPoly(img, [np.array([tip, left, right], np.int32)], 255)
    text = f"{distance_m / 1000:.1f}km" if distance_m >= 1000 else f"{round(distance_m)}m"
    _label(img, text, min(max(tip[0] - 14, 2), W - 40), min(max(tip[1] + (14 if tip[1] < CY else -6), 12), H - 4))


def render_wearer_map(position, annotations, nearby, others=()):
    """Return PNG bytes for the wearer at `position` ({'lat','lon', optional 'heading_deg'})."""
    origin = (position["lat"], position["lon"])
    span = _range_for(nearby[0]["distance_m"] if nearby else None)
    metres_per_px = span / (CY - 8)
    img = np.zeros((H, W), np.uint8)
    cv2.rectangle(img, (0, 0), (W - 1, H - 1), 90, 1)

    # Range ring at half the span, for a sense of distance.
    cv2.circle(img, (CX, CY), int((span / 2) / metres_per_px), 60, 1, cv2.LINE_AA)

    distances = {n["id"]: n["distance_m"] for n in nearby}
    for item in annotations or []:
        points = ((item.get("geometry") or {}).get("latlon")) or []
        if not points:
            continue
        pixels = [_to_px(lat, lon, origin, metres_per_px) for lat, lon in points]
        inside = [0 <= x < W and 0 <= y < H for x, y in pixels]
        bright = 255 if item.get("severity") == "critical" else 200
        if not any(inside):
            cx = sum(x for x, _ in pixels) / len(pixels)
            cy = sum(y for _, y in pixels) / len(pixels)
            _edge_arrow(img, cx, cy, distances.get(item.get("id"), 0))
            continue
        if len(pixels) >= 3:
            poly = np.array(pixels, np.int32)
            cv2.fillPoly(img, [poly], 150)
            cv2.polylines(img, [poly], True, bright, 2, cv2.LINE_AA)
        else:
            cv2.circle(img, (int(pixels[0][0]), int(pixels[0][1])), 6, bright, -1, cv2.LINE_AA)

    # Other crew members: small hollow squares.
    for other in others:
        x, y = _to_px(other["lat"], other["lon"], origin, metres_per_px)
        if 0 <= x < W and 0 <= y < H:
            cv2.rectangle(img, (int(x) - 4, int(y) - 4), (int(x) + 4, int(y) + 4), 220, 1)

    # Wearer: ring and dot at the centre, with a heading tick when known.
    cv2.circle(img, (CX, CY), 7, 255, 1, cv2.LINE_AA)
    cv2.circle(img, (CX, CY), 3, 255, -1, cv2.LINE_AA)
    heading = position.get("heading_deg")
    if heading is not None:
        rad = math.radians(heading)
        cv2.line(img, (CX, CY), (int(CX + 16 * math.sin(rad)), int(CY - 16 * math.cos(rad))), 255, 2, cv2.LINE_AA)

    # North arrow, top left.
    cv2.fillPoly(img, [np.array([(16, 6), (10, 19), (22, 19)], np.int32)], 200)
    _label(img, "N", 12, 31)

    # Scale bar, bottom left: the range ring's radius.
    bar_m = span / 2
    bar_px = int(bar_m / metres_per_px)
    cv2.line(img, (8, H - 10), (8 + bar_px, H - 10), 220, 2)
    _label(img, f"{bar_m / 1000:g} km" if bar_m >= 1000 else f"{bar_m:g} m", 12 + bar_px, H - 6)

    ok, png = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("Could not encode wearer map")
    return png.tobytes()
