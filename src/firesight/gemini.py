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


FIRE_SECTORS = ["upper-left", "upper", "upper-right", "left", "center", "right",
                "lower-left", "lower", "lower-right", "none"]


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
            "fire_sector": {"type": "string", "enum": FIRE_SECTORS},
        },
        "required": ["detected", "priority", "headline", "instructions", "fire_sector"],
        "additionalProperties": False,
    }


def _load_scenario():
    """Field context (wind, routes, crews) from FIRESIGHT_SCENARIO, a JSON file path. None if unset."""
    path = os.getenv("FIRESIGHT_SCENARIO", "").strip()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as file:
            return json.load(file)
    except (OSError, ValueError) as error:
        raise GeminiConfigurationError(f"Could not read FIRESIGHT_SCENARIO file {path}: {error}") from error


def _tactical_prompt(scenario):
    return (
        "You are a wildfire incident assistant writing heads-up-display alerts for a "
        "firefighter on the ground. You get one drone image and the field context below. "
        "Use the image for where flames and smoke are and how intense they look. Use ONLY "
        "the field context for distances, routes, safe zones, wind, hazards and crews; never "
        "invent any that are not in it. Treat the top of the image as straight ahead of the "
        "wearer. Set detected=true only for visible flames or fire smoke, not sunsets, "
        "clouds, dust or fog. priority: critical if the wearer must act now, warning if "
        "they should be ready to move, info if nothing urgent. headline: the single most "
        "important situation, under 40 characters, e.g. 'Fire spreading ahead and right'. "
        "instructions: 2 to 4 short imperative actions, most urgent first, each under 40 "
        "characters, e.g. 'Move down-right to creek trail' or 'Do NOT go back - spot fire'. "
        "fire_sector: where the main fire is in the image, or none. If detected=false, "
        "return priority=info, headline='No fire detected in frame', no instructions and "
        "fire_sector=none.\n\nField context:\n" + json.dumps(scenario, indent=2)
    )


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

    scenario = _load_scenario()
    prompt = _tactical_prompt(scenario) if scenario else (
        "You are a visual wildfire detection model analyzing one drone image. "
        "Return only the requested JSON fields. Set detected=true only when visible "
        "flames or fire-generated smoke support an active wildfire; do not mistake "
        "sunset, clouds, dust, fog, or warm-colored objects for fire. Use critical "
        "for clear active wildfire, warning for plausible but uncertain evidence, "
        "and info when no fire is visible. Keep the headline and each instruction "
        "under 40 characters. Instructions must be brief and describe only visible "
        "relative image locations. Never invent distances, compass directions, safe "
        "routes, crew locations, or evacuation advice. Set fire_sector to where the main "
        "fire is in the image, or none. If detected=false, return priority=info, "
        "headline='No fire detected in frame', no instructions and fire_sector=none."
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

    detected = result.pop("detected", False)
    sector = result.pop("fire_sector", "none")
    result["id"] = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    result["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    alert = validate_alert(result)
    # Kept alongside the glasses contract so the demo map can place the fire.
    alert["fire_sector"] = sector if detected and sector in FIRE_SECTORS else "none"
    return alert
