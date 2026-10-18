"""Gemini vision-language inference for individual JPEG and PNG frames."""
import json
import os
from datetime import datetime, timezone

from firesight.alerts import validate_alert

DEFAULT_MODEL = "gemini-3.8-flash"
MAX_IMAGE_BYTES = 14 * 1024 * 1024


class GeminiConfigurationError(ValueError):
    """Gemini detection was selected but its API key is missing."""


class GeminiRequestError(RuntimeError):
    """Gemini could not analyze the image or returned an invalid response."""


def _response_schema():
    return {
        "type": "object",
        "properties": {
            "detected": {"type": "boolean"},
            "priority": {"type": "string", "enum": ["critical", "warning", "info"]},
            "headline": {"type": "string"},
            "instructions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["detected", "priority", "headline", "instructions"],
    }


def analyze_image_with_gemini(image_bytes, media_type):
    """Send one frame to Gemini's multimodal API and return a glasses alert."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise GeminiConfigurationError("Gemini detector requires GEMINI_API_KEY")
    if not image_bytes:
        raise ValueError("Frame image is empty")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large for Gemini inline input; use an image under 14 MiB")
    if media_type not in ("image/jpeg", "image/png"):
        raise ValueError("Frame must be a JPEG or PNG image")

    prompt = (
        "You are a visual wildfire detection model analyzing one drone image. "
        "Return only the requested JSON fields. Set detected=true only when visible "
        "flames or fire-generated smoke support an active wildfire; do not mistake "
        "sunset, clouds, dust, fog, or warm-colored objects for fire. Use critical "
        "for clear active wildfire, warning for plausible but uncertain evidence, "
        "and info when no fire is visible. Keep the headline and each instruction "
        "under 40 characters. Instructions must be brief and describe only visible "
        "relative image locations. Never invent distances, compass directions, safe "
        "routes, crew locations, or evacuation advice. If detected=false, return "
        "priority=info, headline='No fire detected in frame', and no instructions."
    )
    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=[
                genai.types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=media_type,
                ),
                prompt,
            ],
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_response_schema(),
                temperature=0,
            ),
        )
    except Exception as error:
        raise GeminiRequestError(
            f"Gemini vision request failed ({type(error).__name__}): {error}"
        ) from error

    try:
        result = json.loads(response.text)
    except (AttributeError, TypeError, ValueError) as error:
        raise GeminiRequestError("Gemini returned an invalid JSON detection response") from error

    if not isinstance(result, dict) or not isinstance(result.get("detected"), bool):
        raise GeminiRequestError("Gemini returned an invalid detection result")
    if not result["detected"]:
        result = {
            "priority": "info",
            "headline": "No fire detected in frame",
            "instructions": [],
        }
    else:
        result["priority"] = result.get("priority", "warning")
        if result["priority"] not in ("critical", "warning", "info"):
            result["priority"] = "warning"
        headline = result.get("headline", "Possible fire detected")
        result["headline"] = headline[:40] if isinstance(headline, str) else "Possible fire detected"
        instructions = result.get("instructions", [])
        if not isinstance(instructions, list):
            instructions = []
        result["instructions"] = [line[:40] for line in instructions if isinstance(line, str)][:5]

    result.pop("detected", None)
    result["id"] = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    result["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return validate_alert(result)
