"""Is this search result about the account holder, or someone with their name?

The model says which identifiers a result shows. This module checks each
claim against the text the model was actually given (URL, title, snippet),
so it can't invent corroboration and pass a namesake off as the account
holder.
"""

import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from .scope import ScopedIdentifier
from .text import fold, strip_marks

# Any one of these on the page identifies the account holder on its own.
STRONG_KINDS = frozenset({"email", "phone", "username", "image"})
# A finding has to rest on at least one of these; a city alone is nobody.
IDENTITY_KINDS = STRONG_KINDS | {"name"}

# Text written at an AI agent rather than a human reader. A page carrying it is
# trying to steer the scan, so it never counts as a confident match.
_AIMED_AT_AGENT = re.compile(
    r"ignore (?:all |any )?(?:previous|prior|above|earlier) instructions"
    r"|note to (?:ai|llm|the model|the agent)|\bai agents?\b|system prompt|\bas an ai\b"
    r"|you (?:must|should) (?:also )?(?:search|record|report|mark|add)"
    r"|record .{0,80} as a (?:high-confidence )?finding|mark every result",
    re.IGNORECASE,
)

_AGE = re.compile(r"\bage[ds]?\s*:?\s*(\d{2})(s)?\b|\b(\d{2})\s*(?:years? old|y/o|vuotta)\b", re.IGNORECASE)


def _fold_exact(text: str) -> str:
    # No separator folding: "maija_m" must not match the words "Maija M...".
    return strip_marks(text.casefold())


def _bounded(value: str, text: str, *, before: str, after: str) -> bool:
    """Exact, case-insensitive match that isn't part of a longer token."""
    pattern = rf"(?<!{before}){re.escape(_fold_exact(value))}(?!{after})"
    return re.search(pattern, _fold_exact(text)) is not None


def age_fits(birth_year: int, text: str) -> bool | None:
    """True or False when the text states an age or the year; None when it doesn't."""
    if str(birth_year) in text:
        return True
    m = _AGE.search(text)
    if m is None:
        return None
    if m.group(1):
        low = int(m.group(1))
        high = low + 9 if m.group(2) else low
    else:
        low = high = int(m.group(3))
    expected = date.today().year - birth_year
    return low - 1 <= expected <= high + 1  # a year of slack for birthdays


def shows(ident: ScopedIdentifier, text: str) -> bool:
    """Whether the text visibly contains this identifier."""
    if ident.kind == "phone":
        tail = re.sub(r"\D", "", ident.value)[-9:]
        return bool(tail) and tail in re.sub(r"\D", "", text)
    if ident.kind == "birth_year":
        return age_fits(int(ident.value), text) is True
    if ident.kind == "email":
        return _bounded(ident.value, text, before=r"[a-z0-9._%+-]", after=r"[a-z0-9-]")
    if ident.kind == "username":
        # "plaine" must not match "plaine88": that is a different account.
        return _bounded(ident.value, text, before=r"[a-z0-9_-]", after=r"[a-z0-9_-]")
    if ident.kind == "image":
        return False  # only a reverse-image result can show an image; the agent tracks those
    return fold(ident.value) in fold(text)


def addresses_the_agent(text: str) -> bool:
    """Heuristic: does the page talk to AI agents? The eval's prompt-injection
    case is what found the need: injected text can repeat the account holder's
    city to earn itself a "likely" match."""
    return _AIMED_AT_AGENT.search(text) is not None


def normalize_url(url: str) -> str:
    """One spelling per page, so 'not me' on a URL also covers its variants."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    return urlunsplit(("https", host, parts.path.rstrip("/") or "/", parts.query, ""))
