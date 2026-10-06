"""Small in-process rate limiter for the single-process FabOS API.

The limiter intentionally fails closed for bursts while remaining dependency-free.
For multi-worker deployments, place a shared reverse-proxy/API rate limiter in front
of FabOS as well; this class is defense-in-depth, not a distributed limiter.
"""
from collections import defaultdict, deque
from threading import Lock
import time


def request_client_key(request):
    """Return the public client address supplied by the trusted local proxy.

    Production binds the API to loopback and exposes it only through Caddy, so
    X-Forwarded-For is used for the real remote client. Direct external access to
    the API port must remain blocked; otherwise forwarded headers are spoofable.
    """
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",", 1)[0].strip()
    return real_ip or forwarded or (request.client.host if request.client else "unknown")


class RateLimiter:
    # Cap on distinct client keys so a stream of unique throwaway keys cannot
    # grow the table without bound. Oldest-inserted keys are evicted first.
    MAX_KEYS = 10000

    def __init__(self, limit, window_seconds):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._hits = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key):
        """Drop stale hits for key; remove idle keys entirely."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        hits = self._hits.get(key)
        if hits is None:
            return now, None
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return now, None
        return now, hits

    def allow(self, key):
        key = str(key or "unknown")
        with self._lock:
            now, hits = self._prune(key)
            if hits is not None and len(hits) >= self.limit:
                return False
            if hits is None:
                if len(self._hits) >= self.MAX_KEYS:
                    self._hits.pop(next(iter(self._hits)))
                hits = self._hits[key]
            hits.append(now)
            return True

    def retry_after(self, key):
        key = str(key or "unknown")
        with self._lock:
            now, hits = self._prune(key)
            if not hits:
                return 0
            return max(0, int(self.window_seconds - (now - hits[0]) + 0.999))
