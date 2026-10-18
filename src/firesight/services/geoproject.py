"""Cast image pixels onto the ground using the camera block that Beagle Eyes' gps_tf publishes.

ENU z is height above ground, so the ground is the plane z = 0.
"""
import math

MAX_RANGE_M = 150.0


def pixel_to_ground(camera, u, v, max_range=MAX_RANGE_M):
    """Return ([east, north, 0], clamped) for pixel (u, v), or None if the camera is unusable.

    Rays at or above the horizon, or hitting the ground beyond max_range, are clamped to
    max_range along the ray's horizontal direction and reported with clamped=True.
    """
    fx, fy, cx, cy = camera["intrinsics"]
    right, down, forward = camera["axes_enu"]
    px, py, pz = camera["enu"]
    a, b = (u - cx) / fx, (v - cy) / fy
    d = [a * right[i] + b * down[i] + forward[i] for i in range(3)]
    horizontal = math.hypot(d[0], d[1])
    if horizontal < 1e-9:
        return None
    if d[2] < -1e-6 and pz > 0:
        t = -pz / d[2]
        if t * horizontal <= max_range:
            return [px + t * d[0], py + t * d[1], 0.0], False
    scale = max_range / horizontal
    return [px + scale * d[0], py + scale * d[1], 0.0], True


def enu_to_latlon(enu, origin):
    """Local tangent-plane ENU (metres) to [lat, lon] around origin {'lat','lon'}; cm-accurate under ~1 km."""
    lat = math.radians(origin["lat"])
    e2 = 0.00669437999014
    w = math.sqrt(1 - e2 * math.sin(lat) ** 2)
    meridional = 6378137.0 * (1 - e2) / w ** 3
    prime = 6378137.0 / w
    return [origin["lat"] + math.degrees(enu[1] / meridional),
            origin["lon"] + math.degrees(enu[0] / (prime * math.cos(lat)))]
