"""Decode and analyze one uploaded JPEG or PNG frame."""
import cv2
import numpy as np

from firesight.alerts import build_alert
from firesight.vision import analyze_image, rank_fire_cells

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png"}


def analyze_frame(image_bytes, media_type, rows=4, cols=4, top=3, width=640):
    normalized_type = media_type.split(";", 1)[0].strip().lower()
    if normalized_type not in SUPPORTED_IMAGE_TYPES:
        raise ValueError("Frame must be a JPEG or PNG image")
    if not image_bytes:
        raise ValueError("Frame image is empty")
    if rows < 1 or cols < 1 or top < 0:
        raise ValueError("Grid dimensions must be positive and top cannot be negative")

    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode frame; send a valid JPEG or PNG")
    if width > 0 and image.shape[1] > width:
        scale = width / image.shape[1]
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    fire, intensity = analyze_image(image)
    targets, fire_fraction = rank_fire_cells(fire, intensity, rows, cols, top)
    return build_alert(targets, fire_fraction, rows, cols)
