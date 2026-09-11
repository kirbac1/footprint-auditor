"""Is this search result about the account holder, or someone with their name?

The model says which identifiers a result shows. This module checks each
claim against the text the model was actually given (URL, title, snippet),
so it can't invent corroboration and pass a namesake off as the account
holder.
"""

import re
import unicodedata
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from .scope import ScopedIdentifier

# Any one of these on the page identifies the account holder on its own.
STRONG_KINDS = frozenset({"email", "phone", "username", "image"})
# A finding has to rest on at least one of these; a city alone is nobody.
IDENTITY_KINDS = STRONG_KINDS | {"name"}

_AGE = re.compile(r"\bage[ds]?\s*:?\s*(\d{2})(s)?\b|\b(\d{2})\s*(?:years? old|y/o|vuotta)\b", re.IGNORECASE)


def _strip_marks(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def fold(text: str) -> str:
    """Case- and accent-insensitive, URL separators as spaces, so the name
    'Meikäläinen' matches the slug 'maija-meikalainen'."""
    t = re.sub(r"[-_./+%]+", " ", _strip_marks(text).casefold())
    return " ".join(t.split())


def _fold_exact(text: str) -> str:
    # No separator folding: "maija_m" must not match the words "Maija M...".
    return _strip_marks(text).casefold()


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
    if ident.kind in {"email", "username"}:
        return _fold_exact(ident.value) in _fold_exact(text)
    if ident.kind == "image":
        return False  # only a reverse-image result can show an image; the agent tracks those
    return fold(ident.value) in fold(text)


def normalize_url(url: str) -> str:
    """One spelling per page, so 'not me' on a URL also covers its variants."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.")
    return urlunsplit(("https", host, parts.path.rstrip("/") or "/", parts.query, ""))
