"""Snowflake Cortex vision inference for individual JPEG and PNG frames."""
import base64
import json
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from firesight.alerts import validate_alert

SUPPORTED_DETECTORS = {"auto", "opencv", "snowflake"}
MAX_IMAGE_BYTES = 14 * 1024 * 1024  # Leave room for base64 and JSON under Snowflake's 20 MiB cap.
DEFAULT_MODEL = "openai-gpt-5"
REQUEST_TIMEOUT_SECONDS = 45


class SnowflakeConfigurationError(ValueError):
    """Snowflake detection was selected but its credentials are incomplete."""


class SnowflakeRequestError(RuntimeError):
    """Snowflake Cortex rejected or could not process an image request."""


def selected_detector():
    """Use Snowflake when configured; otherwise preserve the local OpenCV path."""
    detector = os.getenv("FIRESIGHT_DETECTOR", "auto").strip().lower()
    if detector not in SUPPORTED_DETECTORS:
        raise ValueError("FIRESIGHT_DETECTOR must be auto, opencv, or snowflake")
    if detector == "auto":
        return "snowflake" if os.getenv("SNOWFLAKE_ACCOUNT") and os.getenv("SNOWFLAKE_PAT") else "opencv"
    return detector


def _account_url(account):
    account = account.strip().rstrip("/")
    if account.startswith("https://"):
        host = account.split("/", 3)[2]
        if not host or any(char in host for char in "@?#"):
            raise SnowflakeConfigurationError("SNOWFLAKE_ACCOUNT must be an account identifier or HTTPS account URL")
        return f"https://{host}/api/v2/cortex/v1/chat/completions"
    account = re.sub(r"\.snowflakecomputing\.com$", "", account, flags=re.IGNORECASE)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", account):
        raise SnowflakeConfigurationError("SNOWFLAKE_ACCOUNT must be an account identifier or HTTPS account URL")
    return f"https://{account}.snowflakecomputing.com/api/v2/cortex/v1/chat/completions"


def _response_schema():
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "wildfire_frame_alert",
            "schema": {
                "type": "object",
                "properties": {
                    "detected": {"type": "boolean"},
                    "priority": {"type": "string", "enum": ["critical", "warning", "info"]},
                    "headline": {"type": "string", "maxLength": 40},
                    "instructions": {
                        "type": "array",
                        "maxItems": 5,
                        "items": {"type": "string", "maxLength": 40},
                    },
                },
                "required": ["detected", "priority", "headline", "instructions"],
                "additionalProperties": False,
            },
        },
    }


def analyze_image_with_snowflake(image_bytes, media_type):
    """Send one image to Cortex and return the glasses JSON alert contract."""
    account = os.getenv("SNOWFLAKE_ACCOUNT", "").strip()
    pat = os.getenv("SNOWFLAKE_PAT", "").strip()
    if not account or not pat:
        raise SnowflakeConfigurationError(
            "Snowflake detector requires SNOWFLAKE_ACCOUNT and SNOWFLAKE_PAT"
        )
    if not image_bytes:
        raise ValueError("Frame image is empty")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large for the Snowflake request limit; use an image under 14 MiB")
    if media_type not in ("image/jpeg", "image/png"):
        raise ValueError("Frame must be a JPEG or PNG image")

    image_data = base64.b64encode(image_bytes).decode("ascii")
    prompt = (
        "Assess this single drone frame for visible wildfire evidence. Return a concise alert. "
        "Set detected=true only when flames or fire-generated smoke are visibly supported; "
        "do not mistake sunset, clouds, dust, or warm-colored objects for fire. "
        "Use critical for clear active wildfire, warning for plausible but uncertain evidence, "
        "and info when no fire is visible. Keep the headline and each instruction under 40 "
        "characters. Instructions must be short and imperative, using only relative image "
        "locations that are visibly supported. Never invent distances, compass directions, "
        "safe routes, crew locations, or evacuation advice. If detected=false, use priority "
        "info, headline 'No fire detected in frame', and an empty instructions list."
    )
    payload = {
        "model": os.getenv("SNOWFLAKE_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}},
                {"type": "text", "text": prompt},
            ],
        }],
        "response_format": _response_schema(),
        "max_completion_tokens": 300,
    }
    request = Request(
        _account_url(account),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {pat}",
            "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            api_response = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read(1000).decode("utf-8", errors="replace")
        raise SnowflakeRequestError(
            f"Snowflake Cortex returned HTTP {error.code}: {detail}"
        ) from error
    except (URLError, TimeoutError) as error:
        raise SnowflakeRequestError(f"Could not reach Snowflake Cortex: {error}") from error
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SnowflakeRequestError("Snowflake Cortex returned an invalid JSON response") from error

    try:
        content = api_response["choices"][0]["message"]["content"]
        result = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise SnowflakeRequestError("Snowflake Cortex response did not contain a valid alert") from error

    if not isinstance(result, dict) or not isinstance(result.get("detected"), bool):
        raise SnowflakeRequestError("Snowflake Cortex returned an invalid detection result")
    if not result["detected"]:
        result = {
            "priority": "info",
            "headline": "No fire detected in frame",
            "instructions": [],
        }
    else:
        result.setdefault("priority", "warning")
        result.setdefault("headline", "Possible fire detected")
        result.setdefault("instructions", [])

    result.pop("detected", None)
    result["id"] = time_milliseconds()
    result["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return validate_alert(result)


def time_milliseconds():
    """Return a millisecond-based identifier, matching the glasses example contract."""
    return str(int(datetime.now(timezone.utc).timestamp() * 1000))
