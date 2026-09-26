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
    def __init__(self, limit, window_seconds):
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._hits = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key):
        key = str(key or "unknown")
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def retry_after(self, key):
        key = str(key or "unknown")
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits.get(key)
            if not hits:
                return 0
            while hits and hits[0] <= cutoff:
                hits.popleft()
            return max(0, int(self.window_seconds - (now - hits[0]) + 0.999)) if hits else 0
