"""Static asset fingerprinting: versioned URLs + immutable cache policy.

- static_url(path) memoizes the SHA-256 digest of the file under static/ and
  returns /static/<path>?v=<digest>. Registered as a Jinja global.
- The no_cache_static middleware in app.py sends `immutable` ONLY when the v
  query parameter equals the current digest; direct, unversioned and stale
  requests stay `no-cache` (no asset copies, no stale deploys).
"""

import hashlib
from functools import lru_cache
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

_DIGEST_LEN = 12


@lru_cache(maxsize=256)
def static_digest(rel_path: str) -> str:
    """First 12 hex chars of the SHA-256 of a file under static/."""
    return hashlib.sha256((STATIC_DIR / rel_path).read_bytes()).hexdigest()[:_DIGEST_LEN]


@lru_cache(maxsize=256)
def static_url(path: str) -> str:
    """Versioned URL for a static asset: /static/<path>?v=<digest>."""
    rel = path.lstrip("/")
    return f"/static/{rel}?v={static_digest(rel)}"


def is_current_digest(path: str, version: str | None) -> bool:
    """True si version == digest actual del asset (immutable cache)."""
    if not version:
        return False
    try:
        return version == static_digest(path)
    except (FileNotFoundError, OSError):
        return False
