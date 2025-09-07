from pathlib import Path
from .config import ALLOWED_DIRS, MAX_BYTES

def must_be_allowed(path_str: str) -> Path:
    p = Path(path_str).expanduser().resolve()
    for base in ALLOWED_DIRS:
        base = base.expanduser().resolve()
        try:
            p.relative_to(base)
            return p
        except ValueError:
            continue
    raise PermissionError(f"Path not allowed: {p}")

def guard_size(data: bytes):
    if len(data) > MAX_BYTES:
        raise ValueError("File too large for this tool")
