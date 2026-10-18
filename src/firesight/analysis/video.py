"""OpenCV video ingestion and sampled JPEG-frame analysis."""
import os

import cv2

from firesight.alerts import build_alert
from firesight.vision import analyze_image, rank_fire_cells


def analyze_video(video_path, sample_seconds=1.0, grid_rows=4, grid_cols=4,
                  top=3, width=640):
    if sample_seconds <= 0:
        raise ValueError("sample_seconds must be positive")
    if grid_rows < 1 or grid_cols < 1 or top < 0:
        raise ValueError("grid dimensions must be positive and top cannot be negative")

    capture = cv2.VideoCapture(os.fspath(video_path))
    if not capture.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_step = max(1, round(fps * sample_seconds)) if fps and fps > 0 else 1
    frame_index = 0
    sampled_frames = 0
    max_fire_fraction = 0.0
    best_targets = []
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % frame_step == 0:
                encoded_ok, jpeg = cv2.imencode(".jpg", frame)
                if not encoded_ok:
                    raise ValueError(f"Could not JPEG-encode video frame {frame_index}")
                image = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError(f"Could not decode JPEG from video frame {frame_index}")
                if width > 0 and image.shape[1] > width:
                    scale = width / image.shape[1]
                    image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                fire, intensity = analyze_image(image)
                targets, fire_fraction = rank_fire_cells(
                    fire, intensity, grid_rows, grid_cols, top
                )
                sampled_frames += 1
                if fire_fraction > max_fire_fraction:
                    max_fire_fraction = fire_fraction
                    best_targets = targets
            frame_index += 1
    finally:
        capture.release()

    if sampled_frames == 0:
        raise ValueError(f"Video contains no readable frames: {video_path}")
    return build_alert(best_targets, max_fire_fraction, grid_rows, grid_cols)
