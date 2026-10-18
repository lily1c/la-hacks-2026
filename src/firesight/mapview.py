"""Render a 288x144 greyscale tactical map for the G2 glasses display.

Placeholder visual: the fire is placed in the frame sector the detector reported
(e.g. "upper-left"), with the wearer and escape route on the opposite side. Size and
exact position are randomized per alert. It is not a real geographic map.
"""
import random

import cv2
import numpy as np

# Largest image container the G2 glasses support.
VIEW_WIDTH = 288
VIEW_HEIGHT = 144

# Fire anchor for each frame direction reported by the detector.
FIRE_X = {"left": 60, "center": 150, "right": 225}
FIRE_Y = {"upper": 38, "center": 72, "lower": 105}


def render_map(seed=None, direction=None):
    """Return PNG bytes. Black is transparent on the glasses; bright values are lit."""
    rng = random.Random(seed)
    no_fire = direction == "none"
    parts = (direction or "upper-right").split("-")
    vertical = next((p for p in parts if p in FIRE_Y), "center")
    horizontal = next((p for p in parts if p in FIRE_X), "center")
    if direction in ("upper", "lower", "center"):
        horizontal = "center"
    fire_left = horizontal == "left"
    # Wearer and safe zone stay on the side away from the fire.
    you = (178, 70) if fire_left else (110, 70)
    safe_zone = (258, 125) if fire_left else (30, 125)
    px = np.zeros((VIEW_HEIGHT, VIEW_WIDTH), dtype=np.uint8)

    # Border so the map area is visible.
    cv2.rectangle(px, (0, 0), (VIEW_WIDTH - 1, VIEW_HEIGHT - 1), 90, 1)

    # Fire: irregular blob in the upper right, brighter at the core.
    if no_fire:
        fx, fy = -1000, -1000  # nothing detected: draw the map without a fire
    else:
        fx, fy = FIRE_X[horizontal] + rng.randint(-10, 10), FIRE_Y[vertical] + rng.randint(-6, 6)
    radius = rng.randint(28, 42)
    yy, xx = np.mgrid[0:VIEW_HEIGHT, 0:VIEW_WIDTH]
    angle = np.arctan2(yy - fy, xx - fx)
    edge = radius * (1 + 0.12 * np.sin(angle * 3 + 0.5) + 0.07 * np.sin(angle * 7 + 1))
    dist = np.hypot(xx - fx, yy - fy)
    shade = np.where((xx + yy) % 3 == 0, 255, np.where(dist < edge * 0.6, 200, 140))
    px = np.maximum(px, np.where(dist < edge, shade, 0).astype(np.uint8))

    # Escape route: dashed line from the wearer down-left to the safe zone.
    (ux, uy), (sx, sy) = you, safe_zone
    steps = 120
    for s in range(0, steps, 12):
        t0, t1 = s / steps, (s + 6) / steps
        start = (round(ux + (sx - ux) * t0), round(uy + (sy - uy) * t0))
        end = (round(ux + (sx - ux) * t1), round(uy + (sy - uy) * t1))
        cv2.line(px, start, end, 220, 2)

    # Wearer: ring with a filled centre.
    cv2.circle(px, you, 8, 255, 1)
    cv2.circle(px, you, 3, 255, -1)

    # Safe zone: hollow square.
    cv2.rectangle(px, (sx - 7, sy - 7), (sx + 7, sy + 7), 255, 2)

    # North arrow, in the top corner away from the fire.
    ax = 270 if fire_left else 18
    cv2.fillPoly(px, [np.array([(ax, 8), (ax - 7, 21), (ax + 7, 21)])], 200)

    ok, png = cv2.imencode(".png", px)
    if not ok:
        raise ValueError("Could not encode map")
    return png.tobytes()
