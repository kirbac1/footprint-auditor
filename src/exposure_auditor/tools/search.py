"""Web search. Bedrock has no server-side web search tool, so we bring our own."""

import html
import re
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
        if r.status_code != 200:
            raise SearchError(f"search provider returned HTTP {r.status_code}")
        items = r.json().get("web", {}).get("results", [])
        return [
            SearchResult(url=i["url"], title=_clean(i.get("title", "")), snippet=_clean(i.get("description", "")))
            for i in items
            if i.get("url")
        ]
