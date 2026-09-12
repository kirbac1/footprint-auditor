"""A tiny, deterministic search engine over one eval case's pages.

Real web search changes daily and costs money per query. Replaying a fixed
set of pages means every run, and every model, sees the same web whatever
queries it chooses, so scores are comparable run to run and a regression
means the agent changed, not the internet.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..agent.matching import fold
from ..tools.search import SearchResult


@dataclass(frozen=True)
class Page:
    url: str
    title: str
    snippet: str
    truth: str  # subject | namesake | unrelated
    injection: bool = False  # carries text aimed at the agent


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


class FixtureSearch:
    """Returns the pages that contain every term of the query (and match its
    site: filter). Long digit runs match on their last nine digits, so a
    number written +358 40... finds the same page as 040...."""

    def __init__(self, pages: list[Page]) -> None:
        self.pages = pages
        self.queries: list[str] = []

    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        self.queries.append(query)
        site = re.search(r"\bsite:(\S+)", query)
        domain = site.group(1).lower().removeprefix("www.") if site else None
        terms = fold(re.sub(r"\bsite:\S+", " ", query).replace('"', " ")).split()
        hits = []
        for page in self.pages:
            host = (urlsplit(page.url).hostname or "").removeprefix("www.")
            if domain and not (host == domain or host.endswith("." + domain)):
                continue
            raw = f"{page.url} {page.title} {page.snippet}"
            text, digits = fold(raw), _digits(raw)
            if all((t[-9:] in digits) if t.isdigit() and len(t) >= 7 else (t in text) for t in terms):
                hits.append(SearchResult(page.url, page.title, page.snippet))
        return hits[:count]
