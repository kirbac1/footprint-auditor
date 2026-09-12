"""Rate limiting shared through the database.

A fixed-window counter per key, incremented with an atomic upsert, so every
API replica sees the same counts without adding Redis to the stack. Per-day
scan quotas are enforced separately, from the scans table itself.
"""

import random
import time

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import RateLimitWindow


class RateLimiter:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], dialect: str) -> None:
        self._sessionmaker = sessionmaker
        self._insert = pg_insert if dialect == "postgresql" else sqlite_insert

    async def hit(self, key: str, limit: int, window_s: int) -> float | None:
        """Count a hit. Returns seconds to wait if over the limit, else None."""
        now = time.time()
        window_start = int(now // window_s * window_s)
        stmt = self._insert(RateLimitWindow).values(key=key, window_start=window_start, count=1)
        stmt = stmt.on_conflict_do_update(
            index_elements=["key", "window_start"], set_={"count": RateLimitWindow.count + 1}
        ).returning(RateLimitWindow.count)
        async with self._sessionmaker() as session:
            count = (await session.execute(stmt)).scalar_one()
            if random.random() < 0.01:  # noqa: S311 - housekeeping, not security
                await session.execute(delete(RateLimitWindow).where(RateLimitWindow.window_start < now - 86_400))
            await session.commit()
        return window_start + window_s - now if count > limit else None
