"""Single-frame fire-color detection and image-grid ranking."""
import cv2
import numpy as np


def fire_color_mask(bgr):
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb).astype(np.int16)
    y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    ycc_rule = (
        (y > cb) & (cr > cb) & (y > y.mean()) & (cr > cr.mean())
        & (np.abs(cb - cr) >= 40)
    )
    hsv_rule = ((hue <= 35) | (hue >= 170)) & (saturation >= 80) & (value >= 150)
    core = (value >= 245) & (y > 230) & (cr > 135)
    return (ycc_rule & hsv_rule) | core, core, hsv


def analyze_image(bgr):
    candidates, core, hsv = fire_color_mask(bgr)
    mask = candidates.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    keep = np.zeros(count, dtype=bool)
    value = hsv[..., 2]
    hue = hsv[..., 0].astype(np.float32)
    for component in range(1, count):
        if int(stats[component, cv2.CC_STAT_AREA]) < 12:
            continue
        pixels = labels == component
        keep[component] = bool(np.any(core[pixels])) or (
            float(value[pixels].std()) >= 8.0 and float(hue[pixels].std()) >= 3.0
        )
    fire = keep[labels]
    return fire, np.where(fire, value, 0).astype(np.uint8)


def _cell_label(row, col):
    return f"{chr(ord('A') + row)}{col + 1}"


def _bounds(row, col, rows, cols, height, width):
    return (row * height // rows, (row + 1) * height // rows,
            col * width // cols, (col + 1) * width // cols)


def rank_fire_cells(fire, intensity, rows=4, cols=4, top=3):
    """Return ranked target cells and fire-pixel fraction for an image."""
    height, width = fire.shape
    coverage = np.zeros((rows, cols), dtype=np.float64)
    brightness = np.zeros((rows, cols), dtype=np.float64)
    for row in range(rows):
        for col in range(cols):
            y0, y1, x0, x1 = _bounds(row, col, rows, cols, height, width)
            region = fire[y0:y1, x0:x1]
            coverage[row, col] = float(region.mean()) if region.size else 0.0
            active = intensity[y0:y1, x0:x1][region]
            brightness[row, col] = float(active.mean()) / 255.0 if active.size else 0.0

    max_coverage = float(coverage.max())
    severity = 0.7 * (coverage / max_coverage if max_coverage else coverage) + 0.3 * brightness
    ordered = sorted(
        ((float(severity[r, c]), r, c) for r in range(rows) for c in range(cols)),
        reverse=True,
    )
    targets = []
    for score, row, col in ordered:
        if len(targets) >= top or score <= 0:
            break
        y0, y1, x0, x1 = _bounds(row, col, rows, cols, height, width)
        region = intensity[y0:y1, x0:x1]
        if region.size and region.max() > 0:
            local_y, local_x = np.unravel_index(np.argmax(region), region.shape)
            x_px, y_px = x0 + int(local_x), y0 + int(local_y)
        else:
            x_px, y_px = (x0 + x1) // 2, (y0 + y1) // 2
        targets.append({"cell": _cell_label(row, col), "severity": round(score, 4)})
    return targets, float(fire.mean())


def frame_direction(cell, rows, cols):
    """Describe the target's relative position in the image frame."""
    row = ord(cell[0]) - ord("A")
    col = int(cell[1:]) - 1
    vertical = "upper" if row < rows / 3 else "lower" if row >= 2 * rows / 3 else "center"
    horizontal = "left" if col < cols / 3 else "right" if col >= 2 * cols / 3 else "center"
    if vertical == "center":
        return horizontal if horizontal != "center" else "center"
    if horizontal == "center":
        return vertical
    return f"{vertical}-{horizontal}"
