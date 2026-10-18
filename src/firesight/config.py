"""Load KEY=VALUE settings (e.g. GEMINI_API_KEY) from a .env file without overriding real environment variables."""
import os
from pathlib import Path


def load_dotenv(*paths):
    """Read the first existing .env among paths (default: ./.env, then the repository root). Returns the file used."""
    candidates = paths or (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env")
    for path in candidates:
        path = Path(path)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.removeprefix("export ").strip(), value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
        return path
    return None
