#!/usr/bin/env python3
"""Analyze one JPEG image and write a JSON wildfire-targeting report.

This is a single-frame color/brightness heuristic. It does not use temporal
flicker, identify smoke or burned ground reliably, or infer GPS coordinates.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

SCHEMA_VERSION = 2


def fire_color_mask(bgr):
    """Return warm-color candidates, bright-core pixels, and HSV values."""
    ycc = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb).astype(np.int16)
    y, cr, cb = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hue, saturation, value = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    ycc_rule = (
        (y > cb)
        & (cr > cb)
        & (y > y.mean())
        & (cr > cr.mean())
        & (np.abs(cb - cr) >= 40)
    )
    hsv_rule = ((hue <= 35) | (hue >= 170)) & (saturation >= 80) & (value >= 150)
    core = (value >= 245) & (y > 230) & (cr > 135)
    candidates = (ycc_rule & hsv_rule) | core
    return candidates, core, hsv


def analyze_image(bgr):
    """Detect heuristic fire-colored regions in one decoded image array."""
    candidates, core, hsv = fire_color_mask(bgr)
    mask = candidates.astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    keep_component = np.zeros(count, dtype=bool)
    value = hsv[..., 2]
    hue = hsv[..., 0].astype(np.float32)
    for component in range(1, count):
        area = int(stats[component, cv2.CC_STAT_AREA])
        if area < 12:
            continue
        pixels = labels == component
        has_bright_core = bool(np.any(core[pixels]))
        # Single-frame variation is only a weak visual cue; it cannot replace flicker.
        varied_brightness = float(value[pixels].std()) >= 8.0
        varied_hue = float(hue[pixels].std()) >= 3.0
        keep_component[component] = has_bright_core or (varied_brightness and varied_hue)

    fire = keep_component[labels]
    intensity = np.where(fire, value, 0).astype(np.uint8)
    return fire, intensity, hsv


def cell_label(row, col):
    return f"{chr(ord('A') + row)}{col + 1}"


def cell_bounds(row, col, rows, cols, height, width):
    return (
        row * height // rows,
        (row + 1) * height // rows,
        col * width // cols,
        (col + 1) * width // cols,
    )


def analyze_grid(fire, intensity, rows, cols, top, hfov, vfov):
    height, width = fire.shape
    max_intensity = max(1.0, float(intensity.max()))
    coverage = np.zeros((rows, cols), dtype=np.float64)
    brightness = np.zeros((rows, cols), dtype=np.float64)
    heat = intensity.astype(np.float32) / max_intensity

    for row in range(rows):
        for col in range(cols):
            y0, y1, x0, x1 = cell_bounds(row, col, rows, cols, height, width)
            region = fire[y0:y1, x0:x1]
            coverage[row, col] = float(region.mean()) if region.size else 0.0
            active = intensity[y0:y1, x0:x1]
            active_pixels = active[region]
            brightness[row, col] = (
                float(active_pixels.mean()) / 255.0 if active_pixels.size else 0.0
            )

    max_coverage = float(coverage.max())
    severity = 0.7 * (coverage / max_coverage if max_coverage else coverage) + 0.3 * brightness
    cells = []
    for row in range(rows):
        for col in range(cols):
            cells.append(
                {
                    "cell": cell_label(row, col),
                    "severity": round(float(severity[row, col]), 4),
                    "fire_coverage": round(float(coverage[row, col]), 6),
                    "mean_flame_intensity": round(float(brightness[row, col]), 4),
                }
            )
    cells.sort(key=lambda item: item["severity"], reverse=True)

    targets = []
    for cell in cells:
        if len(targets) >= top or cell["severity"] <= 0:
            break
        row = (ord(cell["cell"][0]) - ord("A"))
        col = int(cell["cell"][1:]) - 1
        y0, y1, x0, x1 = cell_bounds(row, col, rows, cols, height, width)
        region_heat = heat[y0:y1, x0:x1]
        if region_heat.size and region_heat.max() > 0:
            local_y, local_x = np.unravel_index(np.argmax(region_heat), region_heat.shape)
            x_px, y_px = x0 + int(local_x), y0 + int(local_y)
        else:
            x_px, y_px = (x0 + x1) // 2, (y0 + y1) // 2
        x_norm, y_norm = x_px / width, y_px / height
        targets.append(
            {
                "rank": len(targets) + 1,
                "cell": cell["cell"],
                "x_px": x_px,
                "y_px": y_px,
                "x": round(x_norm, 4),
                "y": round(y_norm, 4),
                "pan_deg": round((x_norm - 0.5) * hfov, 2),
                "tilt_deg": round((0.5 - y_norm) * vfov, 2),
                "severity": cell["severity"],
                "water_share": 0.0,
            }
        )

    total_severity = sum(target["severity"] for target in targets)
    if total_severity:
        for target in targets:
            target["water_share"] = round(target["severity"] / total_severity, 3)

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(fire.astype(np.uint8))
    hotspot_components = sorted(
        range(1, count), key=lambda component: stats[component, cv2.CC_STAT_AREA], reverse=True
    )
    hotspots = []
    for component in hotspot_components[:5]:
        x, y, box_width, box_height, area = map(int, stats[component])
        hotspots.append(
            {
                "centroid_px": [round(float(centroids[component][0]), 1), round(float(centroids[component][1]), 1)],
                "bbox_px": [x, y, box_width, box_height],
                "area_frac": round(area / (height * width), 6),
            }
        )

    return cells, targets, hotspots, coverage, brightness


def write_json_atomic(path, report):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    os.replace(temp_path, path)


def build_parser():
    parser = argparse.ArgumentParser(description="Analyze a JPEG image and write a JSON report.")
    parser.add_argument("image", help="input JPEG image (.jpg or .jpeg)")
    parser.add_argument("--out", help="output JSON path (default: beside the image)")
    parser.add_argument("--grid", default="4x4", help="grid rows x columns, e.g. 4x4")
    parser.add_argument("--top", type=int, default=3, help="maximum watering targets")
    parser.add_argument("--hfov", type=float, default=84.0, help="camera horizontal FOV in degrees")
    parser.add_argument("--vfov", type=float, default=53.0, help="camera vertical FOV in degrees")
    parser.add_argument("--width", type=int, default=640, help="analysis width; 0 keeps original size")
    return parser


def run_image(args):
    extension = os.path.splitext(args.image)[1].lower()
    if extension not in (".jpg", ".jpeg"):
        raise ValueError("Input must have a .jpg or .jpeg extension")
    try:
        rows, cols = (int(value) for value in args.grid.lower().split("x", 1))
    except (TypeError, ValueError) as error:
        raise ValueError("--grid must be in rowsxcols format, such as 4x4") from error
    if rows < 1 or cols < 1 or args.top < 0:
        raise ValueError("Grid dimensions must be positive and --top cannot be negative")

    image = cv2.imread(args.image, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not decode JPEG image: {args.image}")
    original_height, original_width = image.shape[:2]
    scale = min(1.0, args.width / original_width) if args.width > 0 else 1.0
    if scale < 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    fire, intensity, hsv = analyze_image(image)
    height, width = fire.shape
    cells, targets, hotspots, coverage, brightness = analyze_grid(
        fire, intensity, rows, cols, args.top, args.hfov, args.vfov
    )
    fire_fraction = float(fire.mean())
    output_path = args.out or os.path.splitext(args.image)[0] + ".json"
    report = {
        "schema_version": SCHEMA_VERSION,
        "input": {
            "image": os.path.basename(args.image),
            "format": "JPEG",
            "width": original_width,
            "height": original_height,
            "analysis_width": width,
            "analysis_height": height,
        },
        "detection": {
            "method": "single-frame color and brightness heuristic",
            "limitations": [
                "No temporal flicker validation; warm-colored objects can be false positives.",
                "Smoke, burned ground, growth rate, persistence, and GPS are not inferred from one image.",
                "Pan and tilt assume the configured field of view and a centered camera orientation.",
            ],
        },
        "grid": f"{rows}x{cols}",
        "fire_detected": bool(fire.any()),
        "vitals": {
            "fire_frac": round(fire_fraction, 6),
            "mean_flame_intensity": round(float(intensity[fire].mean()) / 255.0, 4) if fire.any() else 0.0,
            "smoke_frac": None,
            "burned_area_frac": None,
        },
        "most_devastated_cell": targets[0]["cell"] if targets else None,
        "watering_priority": targets,
        "hotspots": hotspots,
        "cells": cells,
    }
    write_json_atomic(output_path, report)
    print(output_path)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run_image(args)
    except (OSError, ValueError, cv2.error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())