"""In-memory TTL cache mapping a session token to its validated /v1/auth/me
profile, so autosave-heavy exam traffic doesn't re-validate against the
external auth service on every request.

Single-process only -- fine for this personal-use deployment (see
../AUTH_INTEGRATION.md); would need a shared store (Redis) for multi-worker.
"""
import hashlib
import time
from threading import Lock

from core.config import settings


class _TTLCache:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict]] = {}
        self._lock = Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def get(self, token: str) -> dict | None:
        key = self._key(token)
        with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, value = entry
            if time.monotonic() >= expires_at:
                del self._store[key]
                return None
            return value

    def set(self, token: str, value: dict) -> None:
        key = self._key(token)
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def invalidate(self, token: str) -> None:
        key = self._key(token)
        with self._lock:
            self._store.pop(key, None)


session_cache = _TTLCache(settings.AUTH_CACHE_TTL_SECONDS)
