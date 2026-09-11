"""Reverse-image search interface.

Deliberately no default vendor: the options (TinEye's commercial API, Google
Lens via a SERP reseller, PimEyes-style face search) differ a lot in cost,
terms and in how much of a face-recognition engine they are. Face search in
particular is the capability most easily turned against someone else, so
wiring one in is a product decision, not a default. Implement this Protocol
and pass it to create_app(reverse_image=...).
"""

from typing import Protocol

from .search import SearchResult


class ReverseImageProvider(Protocol):
    async def search(self, image: bytes, count: int = 10) -> list[SearchResult]: ...
