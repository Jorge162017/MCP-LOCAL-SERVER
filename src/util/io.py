from pathlib import Path
from ..sandbox import must_be_allowed, guard_size

def read_bytes_safe(path: str) -> bytes:
    p = must_be_allowed(path)
    data = p.read_bytes()
    guard_size(data)
    return data
