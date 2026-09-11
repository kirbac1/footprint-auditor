"""The scan agent: Claude on Bedrock driving scope-guarded tools.

A manual tool-use loop rather than Bedrock Agents or the SDK tool runner,
because each tool enforces an invariant the model must not be able to
bypass:
- queries stay in scope (ScopeGuard);
- findings can only point at URLs a tool returned in this scan;
- every "this page shows X" claim is checked against the text the model was
  given (matching.py), so a namesake can't be passed off as the account holder.
"""

import asyncio
import itertools
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from ..identifiers import CONTEXT_KINDS
from ..tools.brokers import BrokerRegistry
from ..tools.reverse_image import ReverseImageProvider
from ..tools.search import SearchError, SearchProvider, SearchResult
from .matching import IDENTITY_KINDS, STRONG_KINDS, shows
from .prompts import system_prompt, task_message
from .scope import ScopedIdentifier, ScopeGuard, ToolError

log = logging.getLogger(__name__)

CATEGORIES = [
    "data_broker",
    "people_search",
    "social_profile",
    "possible_impersonation",
    "paste_or_leak",
    "news_or_public_record",
    "other",
]
CONFIDENCE = ["high", "medium", "low"]

SEARCH_TOOL = {
    "name": "search_web",
    "description": (
        "Search the public web. The query must contain one of the in-scope identifiers exactly as "
        "listed; OR, | and AROUND() are rejected. Set site to a bare domain (e.g. spokeo.com) to "
        "restrict results to it, or to an empty string for no restriction. Returns up to 10 results, "
        "each with a result_id you can pass to record_finding."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"query": {"type": "string"}, "site": {"type": "string"}},
        "required": ["query", "site"],
        "additionalProperties": False,
    },
}

RECORD_TOOL = {
    "name": "record_finding",
    "description": (
        "Report a search result, whether it is about the account holder or is a namesake. result_id must "
        "come from a tool result in this scan. matched_identifier_ids lists every in-scope identifier and "
        "context detail that the result's URL, title or snippet visibly shows; each claim is checked "
        "against that text. conflicting_identifier_ids lists context details the result contradicts "
        "(another city, an age that doesn't fit the birth year, a different employer), or is empty. A "
        "result with a conflict and no email, phone or username match is a namesake: it is counted, not "
        "stored. rationale is one or two sentences on why this is, or isn't, the account holder."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "result_id": {"type": "string"},
            "category": {"type": "string", "enum": CATEGORIES},
            "matched_identifier_ids": {"type": "array", "items": {"type": "string"}},
            "conflicting_identifier_ids": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "string", "enum": CONFIDENCE},
            "rationale": {"type": "string"},
        },
        "required": [
            "result_id",
            "category",
            "matched_identifier_ids",
            "conflicting_identifier_ids",
            "confidence",
            "rationale",
        ],
        "additionalProperties": False,
    },
}

REVERSE_IMAGE_TOOL = {
    "name": "reverse_image_search",
    "description": (
        "Find pages that show one of the account holder's images. Pass the id of an in-scope "
        "identifier of kind image. Returns results with result_ids like search_web."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"identifier_id": {"type": "string"}},
        "required": ["identifier_id"],
        "additionalProperties": False,
    },
}


@dataclass
class AgentConfig:
    llm: Any
    model_id: str
    effort: str
    max_turns: int
    max_searches: int
    search: SearchProvider | None
    reverse_image: ReverseImageProvider | None
    brokers: BrokerRegistry


@dataclass(frozen=True)
class RecordedFinding:
    url: str
    title: str
    category: str
    matched_identifier_ids: list[str]
    confidence: str
    rationale: str
    broker_id: str | None
    match_status: str  # likely | unclear


@dataclass
class AgentOutcome:
    status: Literal["completed", "refused", "turn_limit"]
    findings: list[RecordedFinding]
    summary: str
    searches_run: int
    namesakes_excluded: int = 0


class ScanAgent:
    def __init__(
        self,
        config: AgentConfig,
        mode: Literal["exposure", "impersonation"],
        identifiers: list[ScopedIdentifier],
        images: dict[str, bytes] | None = None,
        is_suppressed: Callable[[str], bool] | None = None,
    ) -> None:
        self._cfg = config
        self._mode = mode
        self._identifiers = identifiers
        self._by_id = {i.id: i for i in identifiers}
        self._images = images or {}
        self._is_suppressed = is_suppressed
        self._guard = ScopeGuard(identifiers)
        self._results: dict[str, SearchResult] = {}
        self._image_results: set[str] = set()
        self._next_id = itertools.count(1)
        self._findings: dict[str, RecordedFinding] = {}
        self._searches = 0
        self._namesakes = 0

    def _tool_defs(self) -> list[dict]:
        tools = [SEARCH_TOOL, RECORD_TOOL]
        if self._mode == "impersonation" and self._images:
            tools.append(REVERSE_IMAGE_TOOL)
        return tools

    def _unavailable(self) -> list[str]:
        missing = []
        if self._cfg.search is None:
            missing.append("search_web")
        if self._mode == "impersonation" and self._images and self._cfg.reverse_image is None:
            missing.append("reverse_image_search")
        return missing

    def _outcome(self, status, summary: str) -> AgentOutcome:
        return AgentOutcome(status, list(self._findings.values()), summary, self._searches, self._namesakes)

    async def run(self) -> AgentOutcome:
        system = system_prompt(self._mode, self._cfg.brokers)
        tools = self._tool_defs()
        messages: list[dict] = [
            {"role": "user", "content": task_message(self._identifiers, self._unavailable())}
        ]
        for _ in range(self._cfg.max_turns):
            response = await self._cfg.llm.messages.create(
                model=self._cfg.model_id,
                max_tokens=16000,
                system=system,
                tools=tools,
                messages=messages,
                output_config={"effort": self._cfg.effort},
                # System prompt and tools are identical across turns and scans,
                # so they cache; the per-user identifiers come after, in messages.
                cache_control={"type": "ephemeral"},
            )
            if response.stop_reason == "refusal":
                return self._outcome(
                    "refused",
                    "The model declined to continue this scan. Findings recorded before that point are kept.",
                )
            # Append the full content (thinking blocks included) so the next
            # turn continues the same reasoning.
            messages.append({"role": "assistant", "content": response.content})
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                text = "\n".join(b.text for b in response.content if b.type == "text").strip()
                return self._outcome("completed", text)
            # All results go back in one user message; splitting them teaches
            # the model to stop making parallel calls.
            results = await asyncio.gather(*(self._run_tool(b) for b in tool_uses))
            messages.append({"role": "user", "content": list(results)})
        return self._outcome("turn_limit", "The scan stopped at its turn limit before the agent finished.")

    async def _run_tool(self, block) -> dict:
        try:
            content = await self._dispatch(block.name, block.input or {})
            return {"type": "tool_result", "tool_use_id": block.id, "content": content}
        except ToolError as exc:
            return {"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True}

    async def _dispatch(self, name: str, inp: dict) -> str:
        if name == "search_web":
            return await self._search(str(inp.get("query", "")), str(inp.get("site") or ""))
        if name == "record_finding":
            return self._record(inp)
        if name == "reverse_image_search":
            return await self._reverse_image(str(inp.get("identifier_id", "")))
        raise ToolError(f"Unknown tool {name!r}.")

    def _remember(self, results: list[SearchResult], from_image: bool = False) -> str:
        if not results:
            return "No results."
        out = []
        for r in results:
            rid = f"r{next(self._next_id)}"
            self._results[rid] = r
            if from_image:
                self._image_results.add(rid)
            out.append({"result_id": rid, "url": r.url, "title": r.title, "snippet": r.snippet})
        return json.dumps(out, ensure_ascii=False)

    async def _search(self, query: str, site: str) -> str:
        if self._cfg.search is None:
            raise ToolError("Web search is not configured on this deployment.")
        self._guard.check_query(query)
        if self._searches >= self._cfg.max_searches:
            raise ToolError("The search budget for this scan is used up. Summarize what you have.")
        q = f"{query} site:{ScopeGuard.check_site(site)}" if site.strip() else query
        self._searches += 1
        try:
            return self._remember(await self._cfg.search.search(q, count=10))
        except SearchError as exc:
            raise ToolError(str(exc)) from None

    async def _reverse_image(self, identifier_id: str) -> str:
        image = self._images.get(identifier_id)
        if image is None:
            raise ToolError("identifier_id is not an in-scope image.")
        if self._cfg.reverse_image is None:
            raise ToolError("Reverse-image search is not configured on this deployment.")
        try:
            return self._remember(await self._cfg.reverse_image.search(image, count=10), from_image=True)
        except SearchError as exc:
            raise ToolError(str(exc)) from None

    def _shows(self, ident: ScopedIdentifier, result_id: str, text: str) -> bool:
        if ident.kind == "image":
            return result_id in self._image_results
        return shows(ident, text)

    def _record(self, inp: dict) -> str:
        result_id = str(inp.get("result_id", ""))
        result = self._results.get(result_id)
        if result is None:
            raise ToolError("Unknown result_id. Only results returned by a tool in this scan can be recorded.")
        category = inp.get("category")
        confidence = inp.get("confidence")
        if category not in CATEGORIES or confidence not in CONFIDENCE:
            raise ToolError("category or confidence is not one of the allowed values.")

        matched = list(dict.fromkeys(inp.get("matched_identifier_ids") or []))
        conflicts = list(dict.fromkeys(inp.get("conflicting_identifier_ids") or []))
        unknown = [i for i in matched + conflicts if i not in self._by_id]
        if unknown:
            raise ToolError(f"Not in-scope identifier ids: {', '.join(unknown)}.")
        if not any(self._by_id[i].kind in IDENTITY_KINDS for i in matched):
            raise ToolError(
                "Name at least one email, phone, name, username or image of the account holder that the "
                "result shows. A city or workplace on its own doesn't identify anyone."
            )
        if any(self._by_id[i].kind not in CONTEXT_KINDS for i in conflicts):
            raise ToolError("conflicting_identifier_ids can only list context details (city, birth year, workplace).")

        text = f"{result.url} {result.title} {result.snippet}"
        unseen = [self._by_id[i] for i in matched if not self._shows(self._by_id[i], result_id, text)]
        if unseen:
            listed = ", ".join(f"{i.kind} {i.id}" for i in unseen)
            raise ToolError(
                f"The result's URL, title and snippet don't show: {listed}. "
                "List only identifiers visible there."
            )

        kinds = {self._by_id[i].kind for i in matched}
        strong = bool(kinds & STRONG_KINDS)
        if conflicts and not strong:
            # Someone else with the same name: their data, not the account
            # holder's, so it is counted and never stored.
            self._namesakes += 1
            return "Not recorded: a different person with the same name. Counted as a namesake."
        if self._is_suppressed is not None and self._is_suppressed(result.url):
            return "Not recorded: the account holder has said this page is not about them."
        if result.url in self._findings:
            return "Already recorded."

        match_status = "likely" if strong or kinds & CONTEXT_KINDS else "unclear"
        broker = self._cfg.brokers.match_url(result.url)
        self._findings[result.url] = RecordedFinding(
            url=result.url,
            title=result.title,
            category=category,
            matched_identifier_ids=matched,
            confidence="low" if match_status == "unclear" else confidence,
            rationale=str(inp.get("rationale", ""))[:1000],
            broker_id=broker.id if broker else None,
            match_status=match_status,
        )
        if match_status == "unclear":
            return "Recorded for the account holder to review: only the name links this result to them."
        return "Recorded."
