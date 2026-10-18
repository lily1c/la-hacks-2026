"""Render a 288x144 greyscale tactical map for the G2 glasses display.

Placeholder visual: the layout (wearer, escape route, safe zone) is fixed and the
fire's size and position are randomized per alert. It is not derived from the frame.
"""
import random

import cv2
import numpy as np

# Largest image container the G2 glasses support.
VIEW_WIDTH = 288
VIEW_HEIGHT = 144

YOU = (110, 70)
SAFE_ZONE = (30, 125)


def render_map(seed=None):
    """Return PNG bytes. Black is transparent on the glasses; bright values are lit."""
    rng = random.Random(seed)
    px = np.zeros((VIEW_HEIGHT, VIEW_WIDTH), dtype=np.uint8)

    # Border so the map area is visible.
    cv2.rectangle(px, (0, 0), (VIEW_WIDTH - 1, VIEW_HEIGHT - 1), 90, 1)

    # Fire: irregular blob in the upper right, brighter at the core.
    fx, fy = 200 + rng.randint(-12, 12), 45 + rng.randint(-8, 8)
    radius = rng.randint(30, 48)
    yy, xx = np.mgrid[0:VIEW_HEIGHT, 0:VIEW_WIDTH]
    angle = np.arctan2(yy - fy, xx - fx)
    edge = radius * (1 + 0.12 * np.sin(angle * 3 + 0.5) + 0.07 * np.sin(angle * 7 + 1))
    dist = np.hypot(xx - fx, yy - fy)
    shade = np.where((xx + yy) % 3 == 0, 255, np.where(dist < edge * 0.6, 200, 140))
    px = np.maximum(px, np.where(dist < edge, shade, 0).astype(np.uint8))

    # Escape route: dashed line from the wearer down-left to the safe zone.
    (ux, uy), (sx, sy) = YOU, SAFE_ZONE
    steps = 120
    for s in range(0, steps, 12):
        t0, t1 = s / steps, (s + 6) / steps
        start = (round(ux + (sx - ux) * t0), round(uy + (sy - uy) * t0))
        end = (round(ux + (sx - ux) * t1), round(uy + (sy - uy) * t1))
        cv2.line(px, start, end, 220, 2)

    # Wearer: ring with a filled centre.
    cv2.circle(px, YOU, 8, 255, 1)
    cv2.circle(px, YOU, 3, 255, -1)

    # Safe zone: hollow square.
    cv2.rectangle(px, (sx - 7, sy - 7), (sx + 7, sy + 7), 255, 2)

    # North arrow, top left.
    cv2.fillPoly(px, [np.array([(18, 8), (11, 21), (25, 21)])], 200)

    ok, png = cv2.imencode(".png", px)
    if not ok:
        raise ValueError("Could not encode map")
    return png.tobytes()
