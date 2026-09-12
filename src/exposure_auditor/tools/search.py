"""Web search. Bedrock has no server-side web search tool, so we bring our own."""

import asyncio
import html
import re
import time
from dataclasses import dataclass
from typing import Protocol

import httpx2

_TAG = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str


class SearchError(RuntimeError):
    pass


class RateLimited(SearchError):
    """The provider refused this call for rate reasons; it may work later."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SearchProvider(Protocol):
    async def search(self, query: str, count: int = 10) -> list[SearchResult]: ...


def _clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text or "")).strip()


class BraveSearch:
    URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, http: httpx2.AsyncClient, api_key: str) -> None:
        self._http = http
        self._key = api_key

    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        r = await self._http.get(
            self.URL,
            params={"q": query, "count": min(count, 20)},
            headers={"X-Subscription-Token": self._key, "Accept": "application/json"},
        )
        if r.status_code == 429:
            raise RateLimited("search provider rate limit", _retry_after(r.headers.get("Retry-After")))
        if r.status_code != 200:
            raise SearchError(f"search provider returned HTTP {r.status_code}")
        items = r.json().get("web", {}).get("results", [])
        return [
            SearchResult(url=i["url"], title=_clean(i.get("title", "")), snippet=_clean(i.get("description", "")))
            for i in items
            if i.get("url")
        ]


def _retry_after(value: str | None) -> float | None:
    """Brave sends seconds; anything else we don't try to parse."""
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:
        return None


class PacedSearch:
    """Keeps a minimum gap between searches, and retries a rate-limited one.

    The agent issues its tool calls in parallel and Brave's free tier allows
    one query per second, so an unpaced scan spends its search budget on 429s.
    Calls are serialized: with the free tier there is no concurrency to have.
    """

    def __init__(self, inner: SearchProvider, min_interval_s: float, max_retries: int = 2) -> None:
        self._inner = inner
        self._min_interval = max(0.0, min_interval_s)
        self._max_retries = max(0, max_retries)
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        last: RateLimited | None = None
        for attempt in range(self._max_retries + 1):
            async with self._lock:
                wait = self._next_at - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    return await self._inner.search(query, count)
                except RateLimited as exc:
                    # A refused call still counts against the provider's window,
                    # so back off further each time rather than retrying at pace.
                    backoff = exc.retry_after or self._min_interval * (attempt + 2)
                    self._next_at = time.monotonic() + backoff
                    last = exc
                finally:
                    self._next_at = max(self._next_at, time.monotonic() + self._min_interval)
        raise SearchError(f"search provider is rate limiting this scan ({last})")
