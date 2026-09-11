"""Demo scan mode, for local UI work without AWS or a search API key.

Only the model and the search provider are fake. The real ScanAgent loop,
ScopeGuard, record_finding checks (namesake handling included), persistence
and remediation plan all run, so what the UI shows is what the pipeline does
with these inputs. Every result title starts with [DEMO], the summary says
so, and Settings refuses demo mode in prod.
"""

import json
import re
import unicodedata
from types import SimpleNamespace

from .agent.matching import age_fits, fold, shows
from .agent.scope import ScopedIdentifier
from .identifiers import CONTEXT_KINDS
from .tools.search import SearchResult

_ID_LINE = re.compile(r"^- id=(\S+) kind=(\S+) value=(.+)$", re.MULTILINE)
_PREFERENCE = ("name", "email", "username", "phone")
_CITIES = ("helsinki", "espoo", "vantaa", "tampere", "turku", "oulu", "jyvaskyla", "kuopio", "lahti")


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-") or "you"


def _reply(stop_reason: str, *blocks) -> SimpleNamespace:
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


def _text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def _tool(id: str, name: str, input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id, name=name, input=input)


class DemoSearch:
    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        site = re.search(r"site:(\S+)", query)
        domain = site.group(1).removeprefix("www.") if site else None
        term = re.sub(r"\s*site:\S+", "", query).strip().strip('"')
        slug = _slug(term)
        note = "Synthetic demo result."
        if domain == "instagram.com":
            return [
                SearchResult(f"https://www.instagram.com/{slug}/", f"[DEMO] {term} (@{slug})", note),
                SearchResult(
                    f"https://www.instagram.com/{slug}_official1/",
                    f"[DEMO] {term} (@{slug}_official1)",
                    f"{note} Same profile photo as @{slug}; account created last month.",
                ),
            ]
        if domain:
            return [
                SearchResult(
                    f"https://www.{domain}/{slug}/demo-123",
                    f"[DEMO] {term}, Helsinki, age 30s",
                    f"{note} Lists a phone number, address history and relatives.",
                ),
                # Same name, different person: the namesake check should drop it.
                SearchResult(
                    f"https://www.{domain}/{slug}/demo-456",
                    f"[DEMO] {term}, Oulu, age 70s",
                    f"{note} Lists a landline and a previous address in Kempele.",
                ),
            ]
        return [
            SearchResult(f"https://www.whitepages.com/name/{slug}/demo", f"[DEMO] {term}: phone and address", note),
            SearchResult(
                f"https://pastebin.com/demo{len(slug)}",
                f"[DEMO] Paste containing {term}",
                f"{note} Email address next to a password hash.",
            ),
        ]


def _judge(result: dict, context: list[ScopedIdentifier]) -> tuple[list[str], list[str]]:
    """What a careful model would report: context that matches, and context that conflicts."""
    text = f"{result['url']} {result['title']} {result['snippet']}"
    matched, conflicts = [], []
    for c in context:
        if shows(c, text):
            matched.append(c.id)
        elif c.kind == "city" and any(city in fold(text) for city in _CITIES):
            conflicts.append(c.id)
        elif c.kind == "birth_year" and age_fits(int(c.value), text) is False:
            conflicts.append(c.id)
    return matched, conflicts


class DemoLLM:
    """Plays the model's side of three turns: search, record, summarize."""

    def __init__(self) -> None:
        self.messages = self

    async def create(self, **kwargs) -> SimpleNamespace:
        messages = kwargs["messages"]
        impersonation = "Task: impersonation" in kwargs["system"]
        idents = _ID_LINE.findall(messages[0]["content"])
        term_id, _, term = min(
            (i for i in idents if i[1] in _PREFERENCE), key=lambda i: _PREFERENCE.index(i[1])
        )
        context = [ScopedIdentifier(i, k, v) for i, k, v in idents if k in CONTEXT_KINDS]
        turn = sum(1 for m in messages if m["role"] == "assistant")

        if turn == 0:
            quoted = f'"{term}"'
            if impersonation:
                calls = [_tool("demo-1", "search_web", {"query": quoted, "site": "instagram.com"})]
            else:
                calls = [
                    _tool("demo-1", "search_web", {"query": quoted, "site": "spokeo.com"}),
                    _tool("demo-2", "search_web", {"query": quoted, "site": ""}),
                ]
            return _reply("tool_use", _text("Searching for the in-scope identifiers."), *calls)

        if turn == 1:
            results = []
            for block in messages[-1]["content"]:
                if not block.get("is_error") and block["content"].startswith("["):
                    results += json.loads(block["content"])
            calls = []
            for n, r in enumerate(results, 1):
                matched_context, conflicts = _judge(r, context)
                url = r["url"]
                if "instagram.com" in url:
                    copy = "_official1" in url
                    category = "possible_impersonation" if copy else "social_profile"
                    rationale = (
                        "Same name and photo as the main profile, on a newer account with a username variant."
                        if copy else "Profile under the account holder's name."
                    )
                elif "pastebin.com" in url:
                    category = "paste_or_leak"
                    rationale = "Paste mentions the name next to credentials."
                elif conflicts:
                    category = "people_search"
                    rationale = "Same name, but the location and age belong to someone else."
                else:
                    category = "people_search"
                    rationale = "Listing shows the full name with a phone number and address history."
                calls.append(_tool(f"demo-r{n}", "record_finding", {
                    "result_id": r["result_id"],
                    "category": category,
                    "matched_identifier_ids": [term_id, *matched_context],
                    "conflicting_identifier_ids": conflicts,
                    "confidence": "high" if matched_context else "low",
                    "rationale": rationale,
                }))
            return _reply("tool_use", *calls)

        set_aside = sum("namesake" in b["content"] for b in messages[-1]["content"])
        return _reply(
            "end_turn",
            _text(
                "Demo mode: these findings come from synthetic search results, not the real web. "
                f"Searched for {term}; set aside {set_aside} result{'s' if set_aside != 1 else ''} "
                "about someone else with the same name."
            ),
        )
