"""Alert contract shared by the video analyzer and HTTP API."""
from datetime import datetime, timezone
import time
import uuid

from firesight.vision import frame_direction


def build_alert(targets, fire_fraction, rows=4, cols=4):
    if fire_fraction <= 0:
        priority = "info"
        headline = "No fire detected in frame"
        instructions = []
    else:
        priority = "critical" if fire_fraction >= 0.05 else "warning"
        headline = "Fire detected - use caution"
        instructions = [
            f"Check {direction} frame sector"
            for direction in dict.fromkeys(
                frame_direction(target["cell"], rows, cols) for target in targets[:5]
            )
        ]
    return {
        "id": uuid.uuid4().hex,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "priority": priority,
        "headline": headline[:40],
        "instructions": [line[:40] for line in instructions[:5]],
    }


def validate_alert(payload):
    """Normalize and validate an alert submitted to the latest-alert endpoint."""
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    headline = payload.get("headline")
    if not isinstance(headline, str) or not headline.strip():
        raise ValueError("headline is required and must be a non-empty string")
    instructions = payload.get("instructions", [])
    if not isinstance(instructions, list) or len(instructions) > 5:
        raise ValueError("instructions must be a list with at most 5 lines")
    if any(not isinstance(line, str) or len(line) > 40 for line in instructions):
        raise ValueError("each instruction must be a string of at most 40 characters")
    if len(headline) > 40:
        raise ValueError("headline must be at most 40 characters")
    priority = payload.get("priority", "info")
    if priority not in ("critical", "warning", "info"):
        priority = "info"
    identifier = payload.get("id")
    if identifier is None:
        identifier = str(time.time_ns() // 1_000_000)
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "id": str(identifier),
        "timestamp": timestamp,
        "priority": priority,
        "headline": headline,
        "instructions": instructions,
    }
