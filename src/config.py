from pathlib import Path

ALLOWED_DIRS = [Path.cwd() / "samples", Path.home() / "datasets", Path.home() / "docs"]
TIMEOUT_SECONDS = 20
MAX_BYTES = 25 * 1024 * 1024  # lectura segura
