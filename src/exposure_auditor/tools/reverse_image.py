"""Reverse-image search: where else on the web does this photo appear?

Used only by the impersonation check, to find profiles reusing the account
holder's picture.

The vendor is a deliberate choice, not a default. The options differ in what
they actually do: TinEye matches *copies of the image*, while a face-search
engine finds *other photos of the person*. This ships with TinEye for that
reason. Photos here are attested, not proven -- someone can upload a stranger's
face -- so a face-search engine wired in behind this interface would turn an
auditing tool into a way of tracking whoever the uploader chose. Copy-matching
degrades far more safely: pointed at someone else's photo it finds reposts of
that file, not the person.

Set EA_TINEYE_API_KEY to switch it on. Without a key the tool isn't offered to
the agent at all, and the UI says so.
"""

from typing import Protocol
from urllib.parse import urlsplit

import httpx2

from .search import SearchError, SearchResult


class ReverseImageProvider(Protocol):
    async def search(self, image: bytes, count: int = 10) -> list[SearchResult]: ...


class TinEyeSearch:
    """https://services.tineye.com/developers/tineyeapi/api_reference

    POST multipart to /rest/search/ with the image bytes; each match carries
    backlinks, which are the pages the image was found on.
    """

    def __init__(self, http: httpx2.AsyncClient, api_key: str, base_url: str = "https://api.tineye.com/rest") -> None:
        self._http = http
        self._key = api_key
        self._url = base_url.rstrip("/") + "/search/"

    async def search(self, image: bytes, count: int = 10) -> list[SearchResult]:
        try:
            r = await self._http.post(
                self._url,
                headers={"x-api-key": self._key},
                params={"limit": min(count, 100), "sort": "score", "order": "desc"},
                files={"image_upload": ("image.jpg", image)},
            )
        except Exception as exc:
            raise SearchError(f"reverse-image provider unreachable: {type(exc).__name__}") from None
        if r.status_code != 200:
            raise SearchError(f"reverse-image provider returned HTTP {r.status_code}")
        body = r.json()
        if body.get("code", 200) != 200:
            raise SearchError("; ".join(body.get("messages") or ["reverse-image search failed"])[:200])
        return _results(body.get("results", {}).get("matches") or [], count)


def _results(matches: list[dict], count: int) -> list[SearchResult]:
    """One result per page the image appears on, not per match: a single match
    can be linked from many pages, and a page is what a finding points at."""
    out: list[SearchResult] = []
    seen: set[str] = set()
    for match in matches:
        score = match.get("score")
        for link in match.get("backlinks") or []:
            page = (link.get("backlink") or "").strip()
            if not page or page in seen:
                continue
            seen.add(page)
            host = urlsplit(page).hostname or "this page"
            crawled = (link.get("crawl_date") or "").split(" ")[0]
            detail = f"Copy of the photo found on {host}"
            if score is not None:
                detail += f" (match score {score})"
            if crawled:
                detail += f", seen {crawled}"
            out.append(SearchResult(url=page, title=host, snippet=detail))
            if len(out) >= count:
                return out
    return out
