"""Feed drone-like frames to the FireSight API so each one is analyzed and sent to the glasses.

    python scripts/frame_feed.py                       # dummy frames made from wildfire.jpeg
    python scripts/frame_feed.py --dir path/to/images  # your own JPEG/PNG frames
    python scripts/frame_feed.py --url https://...     # another backend
    INGEST_TOKEN=... python scripts/frame_feed.py      # backend with PUBLIC_DEPLOYMENT=true

Frames are real images and go through the real detector (POST /frame); only the
dummy frames themselves are synthetic crops/flips of one wildfire photo.
"""
import argparse
import itertools
import json
import os
import time
import urllib.request
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent


def dummy_frames(path):
    """Variations of one photo so the fire lands in different frame sectors."""
    img = cv2.imread(str(path))
    if img is None:
        raise SystemExit(f"Could not read {path}")
    h, w = img.shape[:2]
    zoom = img[0:int(h * .6), int(w * .35):int(w * .85)]
    return [
        ("wide view, fire upper", img),
        ("smoke only, no flames", cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)),
        ("drone turned, fire upper-left", cv2.flip(img, 1)),
        ("close pass, fire upper-left", zoom),
        ("descending, fire lower", cv2.copyMakeBorder(img[0:int(h * .5), :], int(h * .5), 0, 0, 0, cv2.BORDER_REFLECT)),
        ("close pass, fire upper-right", cv2.flip(zoom, 1)),
    ]


def folder_frames(folder):
    files = sorted(p for p in Path(folder).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not files:
        raise SystemExit(f"No JPEG/PNG files in {folder}")
    return [(p.name, cv2.imread(str(p))) for p in files]


def send(url, token, image):
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    request = urllib.request.Request(
        url, data=jpeg.tobytes(), method="POST",
        headers={"Content-Type": "image/jpeg", **({"Authorization": f"Bearer {token}"} if token else {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8790", help="backend base URL")
    parser.add_argument("--dir", help="folder of JPEG/PNG frames (default: dummy frames)")
    parser.add_argument("--interval", type=float, default=6, help="seconds between frames")
    args = parser.parse_args()

    frames = folder_frames(args.dir) if args.dir else dummy_frames(ROOT / "wildfire.jpeg")
    endpoint = args.url.rstrip("/") + "/frame"
    token = os.getenv("INGEST_TOKEN", "")
    print(f"Feeding {len(frames)} frames to {endpoint} every {args.interval:g}s (Ctrl+C to stop)\n", flush=True)

    for name, image in itertools.cycle(frames):
        started = time.time()
        try:
            alert = send(endpoint, token, image)
            print(f"{name:32} -> [{alert['priority']}] {alert['headline']} | {'; '.join(alert['instructions'])}", flush=True)
        except Exception as error:  # keep feeding through backend restarts
            print(f"{name:32} -> failed: {error}", flush=True)
        time.sleep(max(0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    main()
