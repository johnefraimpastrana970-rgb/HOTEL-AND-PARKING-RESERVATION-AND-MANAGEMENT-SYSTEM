"""Shared Redis-backed API rate limiting with a local-development fallback."""

from __future__ import annotations

import ipaddress
import math
import threading
import time
from typing import Any

import redis

from . import config


class RateLimiterUnavailable(Exception):
    """Raised when the configured shared rate-limit store cannot be reached."""


class RateLimiter:
    _INCREMENT_SCRIPT = """
local count = redis.call("INCR", KEYS[1])
local ttl = redis.call("TTL", KEYS[1])
if count == 1 or ttl < 0 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
return {count, redis.call("TTL", KEYS[1])}
"""

    def __init__(self, redis_url: str = "") -> None:
        self._redis: Any = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        ) if redis_url else None
        self._lock = threading.Lock()
        self._windows: dict[str, tuple[int, float]] = {}
        self._checks = 0

    @property
    def mode(self) -> str:
        return "redis" if self._redis is not None else "local"

    def check(self, key: str, limit: int, window_seconds: int) -> int | None:
        if limit < 1 or window_seconds < 1:
            raise ValueError("Rate limits and windows must be positive integers.")
        if self._redis is not None:
            try:
                count, ttl = self._redis.eval(
                    self._INCREMENT_SCRIPT, 1, key, window_seconds,
                )
            except redis.RedisError as error:
                raise RateLimiterUnavailable from error
            if int(count) > limit:
                return max(1, int(ttl))
            return None

        now = time.monotonic()
        with self._lock:
            self._checks += 1
            if self._checks % 256 == 0:
                self._windows = {
                    stored_key: window
                    for stored_key, window in self._windows.items()
                    if window[1] > now
                }
            count, expires_at = self._windows.get(key, (0, now + window_seconds))
            if expires_at <= now:
                count, expires_at = 0, now + window_seconds
            count += 1
            self._windows[key] = (count, expires_at)
            if count > limit:
                return max(1, math.ceil(expires_at - now))
        return None

    def ping(self) -> None:
        if self._redis is None:
            return
        try:
            self._redis.ping()
        except redis.RedisError as error:
            raise RateLimiterUnavailable from error


TRUSTED_PROXY_NETWORKS = tuple(
    ipaddress.ip_network(cidr, strict=False) for cidr in config.TRUSTED_PROXY_CIDRS
)
RATE_LIMITER = RateLimiter(config.REDIS_URL)
