"""Detector selection for JPEG and PNG frames."""
import os

SUPPORTED_DETECTORS = {"auto", "opencv", "gemini"}


def selected_detector():
    """Use Gemini when configured; otherwise default to the local OpenCV detector."""
    detector = os.getenv("FIRESIGHT_DETECTOR", "auto").strip().lower()
    if detector not in SUPPORTED_DETECTORS:
        raise ValueError("FIRESIGHT_DETECTOR must be auto, opencv, or gemini")
    if detector == "auto":
        return "gemini" if os.getenv("GEMINI_API_KEY", "").strip() else "opencv"
    return detector
