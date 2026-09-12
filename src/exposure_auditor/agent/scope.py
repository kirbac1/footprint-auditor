"""The scope guard: the agent can only ever look for the account holder.

This lives in code, not in the prompt. The model composes search queries,
and search results are attacker-controllable text, so an instruction like
"only search for the user" is a request, not a control. Every query the model
issues is checked here before it reaches the search provider.
"""

import re
from dataclasses import dataclass

_BROADENING = re.compile(r"(\bOR\b|\||\bAROUND\(\d+\))")
_SITE = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


class ToolError(Exception):
    """A tool call the agent made that we refuse; returned to it as is_error.

    `code` is a short, content-free reason that goes into the scan trace.
    """

    def __init__(self, message: str, code: str = "rejected") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScopedIdentifier:
    id: str
    kind: str
    value: str  # normalized plaintext; for images, just a label


class ScopeGuard:
    def __init__(self, identifiers: list[ScopedIdentifier]) -> None:
        self._text_terms = [i.value.casefold() for i in identifiers if i.kind in {"email", "name", "username"}]
        # Phones: match on the last 9 digits, so "+358 40 123 4567" and the
        # national "040 123 4567" both count as containing the number.
        self._phone_tails = [re.sub(r"\D", "", i.value)[-9:] for i in identifiers if i.kind == "phone"]

    def check_query(self, query: str) -> None:
        if not query.strip() or len(query) > 300:
            raise ToolError("Query rejected: empty or longer than 300 characters.", "bad_query")
        if _BROADENING.search(query):
            # "<me> OR <someone else>" would pass a contains-check and return
            # results about the other person.
            raise ToolError("Query rejected: OR, | and AROUND() operators are not allowed.", "broadening_operator")
        folded = query.casefold()
        if any(term in folded for term in self._text_terms):
            return
        digits = re.sub(r"\D", "", query)
        if any(tail and tail in digits for tail in self._phone_tails):
            return
        raise ToolError(
            "Query rejected: it must contain one of the in-scope identifiers exactly as listed. "
            "Searching for anyone other than the account holder is not possible.",
            "out_of_scope",
        )

    @staticmethod
    def check_site(site: str) -> str:
        site = site.strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
        if not _SITE.match(site):
            raise ToolError("site must be a bare domain such as spokeo.com", "bad_site")
        return site
