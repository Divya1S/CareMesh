"""Redis backed rate limiting: the first documented Redis use (per the
conventions, every Redis use is justified here).

Why Redis: counters must be shared across API processes and survive a
restart within the window; in process dicts do neither. Fixed window
counters (INCR + EXPIRE) are deliberately simple: good enough to stop
credential stuffing and runaway AI usage in this simulation, and easy to
reason about. A sliding window can replace this behind the same interface
if fairness at window edges ever matters.
"""

from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    retry_after_seconds: int


class RedisRateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def allow(self, key: str, limit: int, window_seconds: int) -> RateDecision:
        full_key = f"rl:{key}"
        count = await self._redis.incr(full_key)
        if count == 1:
            await self._redis.expire(full_key, window_seconds)
        if count <= limit:
            return RateDecision(allowed=True, retry_after_seconds=0)
        ttl = await self._redis.ttl(full_key)
        return RateDecision(allowed=False, retry_after_seconds=max(int(ttl), 1))
