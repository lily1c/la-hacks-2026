#!/usr/bin/env python3
"""CLI for analyzing drone video and writing the glasses alert JSON."""
import argparse
import json
import os
import sys

import cv2

from firesight.video import analyze_video


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyze sampled JPEG frames from a drone video.")
    parser.add_argument("video", help="video file readable by OpenCV")
    parser.add_argument("--out", help="JSON output path (default: beside video)")
    parser.add_argument("--grid", default="4x4", help="grid rows x columns")
    parser.add_argument("--top", type=int, default=3, help="maximum instruction targets")
    parser.add_argument("--width", type=int, default=640, help="analysis width; 0 keeps original")
    parser.add_argument("--sample-seconds", type=float, default=1.0,
                        help="sample interval in seconds")
    args = parser.parse_args(argv)
    try:
        rows, cols = (int(value) for value in args.grid.lower().split("x", 1))
        alert = analyze_video(args.video, args.sample_seconds, rows, cols, args.top, args.width)
        output_path = args.out or os.path.splitext(args.video)[0] + ".json"
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        temp_path = output_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as output:
            json.dump(alert, output, indent=2)
            output.write("\n")
        os.replace(temp_path, output_path)
        print(output_path)
    except (OSError, ValueError, cv2.error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
