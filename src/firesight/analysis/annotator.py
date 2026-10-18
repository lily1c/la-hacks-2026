"""Ask Gemini what to mark on the map: operator prompt + one drone frame -> located annotations."""
import json
import os
import re

import cv2
import numpy as np

from firesight.analysis.gemini import GeminiConfigurationError, GeminiRequestError
from firesight.services.geoproject import enu_to_latlon, pixel_to_ground

# Flash-Lite with minimal thinking is the low-latency tier; override with GEMINI_ANNOTATE_MODEL.
DEFAULT_ANNOTATE_MODEL = "gemini-3.5-flash-lite"
MAX_SIDE_PX = 768
# Suggested kinds; Gemini may coin others (e.g. "car_crash"), each shown with its own colour and toggle.
KINDS = ["incident", "hazard_area", "road_blockage", "vehicle", "person", "tree", "structure", "other"]
AREA_KINDS = {"incident", "hazard_area", "road_blockage"}  # fallback shape when Gemini omits "shape"


def _kind(raw):
    kind = re.sub(r"[^a-z0-9]+", "_", str(raw).lower()).strip("_")[:24]
    return kind or "other"
MAX_ANNOTATIONS = 20


def annotate_model():
    return os.getenv("GEMINI_ANNOTATE_MODEL", "").strip() or DEFAULT_ANNOTATE_MODEL


def _schema():
    return {
        "type": "object",
        "properties": {
            "annotations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                        "kind": {"type": "string"},
                        "shape": {"type": "string", "enum": ["area", "object"]},
                        "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                        "box_2d": {"type": "array", "items": {"type": "integer"}, "minItems": 4, "maxItems": 4},
                        "summary": {"type": "string"},
                    },
                    "required": ["label", "kind", "shape", "severity", "box_2d"],
                },
            }
        },
        "required": ["annotations"],
    }


def _prompt(user_prompt, geo):
    context = ""
    drone = (geo or {}).get("drone")
    if drone:
        context = f" The drone is about {drone.get('height_agl_m')} m above ground, heading {drone.get('heading_true_deg')} degrees true."
    return (
        "You mark things on a map from one drone camera frame. Report only what is clearly visible "
        "and matches the operator instruction below; if nothing matches, return an empty list. "
        "box_2d is [ymin, xmin, ymax, xmax] normalized to 0-1000. kind is a short lowercase snake_case category "
        "(e.g. person, vehicle, tree, incident, hazard_area, road_blockage, or your own such as fire); use the same "
        "kind for the same type of thing. shape is area for a region (affected zone, blocked road) and object for a "
        "single thing (one person, one car, one tree). "
        "label under 30 characters, summary under 80. Describe only what is visible; give no distances, "
        "safe routes or evacuation advice." + context + "\n\nOperator instruction: " + user_prompt
    )


def _shrink(image_bytes):
    """Downscale before upload: smaller images mean fewer tokens and lower latency."""
    frame = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Frame is not a decodable image")
    h, w = frame.shape[:2]
    scale = MAX_SIDE_PX / max(h, w)
    if scale < 1:
        frame = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        raise ValueError("Could not re-encode frame")
    return jpeg.tobytes()


def detect_with_gemini(image_bytes, prompt, geo=None):
    """Return raw annotation dicts (label, kind, severity, box_2d, summary) from Gemini."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiConfigurationError("Set GEMINI_API_KEY to use Gemini annotations")
    small = _shrink(image_bytes)
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        parts = [genai.types.Part.from_bytes(data=small, mime_type="image/jpeg"), _prompt(prompt, geo)]

        def call(thinking):
            kwargs = {"response_mime_type": "application/json", "response_schema": _schema(), "temperature": 0}
            if thinking:
                kwargs["thinking_config"] = genai.types.ThinkingConfig(thinking_level="minimal")
            return client.models.generate_content(
                model=annotate_model(), contents=parts, config=genai.types.GenerateContentConfig(**kwargs))

        try:
            response = call(True)
        except Exception:  # model may not accept thinking_level; retry plainly
            response = call(False)
        data = json.loads(response.text)
    except Exception as error:
        raise GeminiRequestError(f"Gemini annotation request failed ({type(error).__name__}): {error}") from error
    items = data.get("annotations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise GeminiRequestError("Gemini returned an invalid annotation response")
    return items[:MAX_ANNOTATIONS]


def build_annotations(items, geo, frame_id, now, ttl_s=60):
    """Turn raw Gemini items into map annotations placed on the ground; unplaced if there is no camera geometry."""
    camera = (geo or {}).get("camera")
    origin = (geo or {}).get("origin")
    approx = not (geo or {}).get("transform_v_to_e", {}).get("calibrated", False)
    out = []
    for index, item in enumerate(items):
        try:
            ymin, xmin, ymax, xmax = (max(0, min(1000, float(v))) for v in item["box_2d"])
            kind = _kind(item["kind"])
            area = item.get("shape") == "area" if item.get("shape") in ("area", "object") else kind in AREA_KINDS
            record = {
                "id": f"gem-{frame_id}-{index}",
                "source": "gemini",
                "kind": kind,
                "label": str(item.get("label", kind))[:40],
                "severity": item.get("severity") if item.get("severity") in ("critical", "warning", "info") else "info",
                "summary": str(item.get("summary", ""))[:120],
                "box_2d": [ymin, xmin, ymax, xmax],
                "frame_id": frame_id,
                "ts": now,
                "ttl_s": ttl_s,
                "approx": approx,
                "geometry": None,
            }
        except (KeyError, TypeError, ValueError):
            continue
        if camera and origin:
            w, h = camera["image_size"]
            to_px = lambda y, x: (x / 1000.0 * w, y / 1000.0 * h)
            if area:
                pixels = [to_px(ymin, xmin), to_px(ymin, xmax), to_px(ymax, xmax), to_px(ymax, xmin)]
            else:
                pixels = [to_px(ymax, (xmin + xmax) / 2)]  # object sits where its box meets the ground
            hits = [pixel_to_ground(camera, u, v) for u, v in pixels]
            if all(hits):
                enu = [hit[0] for hit in hits]
                latlon = [enu_to_latlon(p, origin) for p in enu]
                record["geometry"] = {"type": "Polygon" if area else "Point",
                                      "enu": [[round(v, 2) for v in p[:2]] for p in enu],
                                      "latlon": [[round(v, 7) for v in p] for p in latlon]}
                record["clamped"] = any(hit[1] for hit in hits)
                drone = camera["enu"]
                record["range_m"] = round(min(((p[0] - drone[0]) ** 2 + (p[1] - drone[1]) ** 2) ** 0.5 for p in enu), 1)
        out.append(record)
    return out
