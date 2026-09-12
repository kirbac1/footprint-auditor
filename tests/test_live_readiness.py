"""What a scan against real credentials needs that a scripted one doesn't:
pacing for a rate-limited search API, a spend ceiling, and a pre-flight check.
"""

import asyncio
import itertools
import time
from types import SimpleNamespace

import pytest
from conftest import reply, text, tool_use

from exposure_auditor.agent.orchestrator import AgentConfig, ScanAgent
from exposure_auditor.agent.scope import ScopedIdentifier
from exposure_auditor.preflight import format_checks, run_checks
from exposure_auditor.tools.brokers import BrokerRegistry
from exposure_auditor.tools.search import PacedSearch, RateLimited, SearchError, SearchResult


class _Recording:
    """A search provider that records when it was called."""

    def __init__(self, fail_times: int = 0, retry_after: float | None = None) -> None:
        self.calls: list[float] = []
        self._fail_times = fail_times
        self._retry_after = retry_after

    async def search(self, query: str, count: int = 10) -> list[SearchResult]:
        self.calls.append(time.monotonic())
        if len(self.calls) <= self._fail_times:
            raise RateLimited("429", self._retry_after)
        return [SearchResult(f"https://example.com/{len(self.calls)}", query, "")]


async def test_parallel_searches_are_paced_not_burst():
    inner = _Recording()
    paced = PacedSearch(inner, min_interval_s=0.05)
    await asyncio.gather(*(paced.search(f"q{i}") for i in range(3)))

    assert len(inner.calls) == 3
    gaps = [b - a for a, b in itertools.pairwise(inner.calls)]
    assert all(gap >= 0.05 for gap in gaps), gaps


async def test_a_rate_limited_search_is_retried_after_the_providers_delay():
    inner = _Recording(fail_times=1, retry_after=0.05)
    results = await PacedSearch(inner, min_interval_s=0.0).search("maija")

    assert len(inner.calls) == 2
    assert results[0].url.endswith("/2")


async def test_a_search_that_keeps_being_rate_limited_gives_up():
    inner = _Recording(fail_times=99, retry_after=0.0)
    with pytest.raises(SearchError, match="rate limiting"):
        await PacedSearch(inner, min_interval_s=0.0, max_retries=1).search("maija")
    assert len(inner.calls) == 2


class _CountingLLM:
    """Answers with a tool call forever, so only a budget can stop the loop."""

    def __init__(self) -> None:
        self.calls = 0
        self.messages = self

    async def create(self, **kwargs):
        self.calls += 1
        response = reply("tool_use", tool_use(f"s{self.calls}", "search_web", {"query": "maija", "site": ""}))
        response.usage = SimpleNamespace(
            input_tokens=100_000, output_tokens=1_000, cache_read_input_tokens=0, cache_creation_input_tokens=0
        )
        return response


async def test_a_scan_stops_at_its_cost_ceiling():
    llm = _CountingLLM()
    # $5/Mtok in, $25/Mtok out: 100k input + 1k output is $0.525 a turn.
    config = AgentConfig(
        llm=llm,
        model_id="claude-opus-5",
        effort="low",
        max_turns=24,
        max_searches=40,
        search=_Recording(),
        reverse_image=None,
        brokers=BrokerRegistry.load(),
        cost_of=lambda i, o, cr, cw: i * 5e-6 + o * 25e-6,
        max_cost_usd=1.0,
    )
    outcome = await ScanAgent(
        config, "exposure", [ScopedIdentifier("n1", "name", "Maija Meikäläinen")]
    ).run()

    assert outcome.status == "cost_limit"
    assert "$1.00" in outcome.summary
    assert llm.calls == 2  # stopped once the running total passed the ceiling
    assert outcome.status != "turn_limit"


async def test_no_ceiling_means_the_turn_limit_still_applies():
    llm = _CountingLLM()
    config = AgentConfig(
        llm=llm,
        model_id="claude-opus-5",
        effort="low",
        max_turns=3,
        max_searches=40,
        search=_Recording(),
        reverse_image=None,
        brokers=BrokerRegistry.load(),
        cost_of=lambda i, o, cr, cw: i * 5e-6 + o * 25e-6,
        max_cost_usd=None,
    )
    outcome = await ScanAgent(config, "exposure", [ScopedIdentifier("n1", "name", "Maija M")]).run()

    assert outcome.status == "turn_limit"
    assert llm.calls == 3


class _OkHibp:
    async def password_range(self, prefix: str) -> list[tuple[str, int]]:
        return [("0018A45C4D1DEF81644B54AB7F969B88D65", 1)]


class _OkLLM:
    def __init__(self) -> None:
        self.messages = self

    async def create(self, **kwargs):
        response = text("ready")
        response.usage = SimpleNamespace(input_tokens=10, output_tokens=2)
        return response


async def test_preflight_reports_what_a_real_scan_still_needs(settings):
    checks = await run_checks(settings, llm=_OkLLM(), search=_Recording(), hibp=_OkHibp())
    by_name = {c.name: c for c in checks}

    assert by_name["model"].ok
    assert by_name["web search"].ok
    # The test settings run on SQLite created by create_all, not by Alembic.
    assert not by_name["database"].ok

    report = format_checks(checks)
    assert "Not ready" in report and "database" in report


async def test_preflight_blocks_a_scan_while_demo_mode_is_on(settings):
    settings = settings.model_copy(update={"demo_scans": True})
    checks = await run_checks(settings, llm=_OkLLM(), search=_Recording(), hibp=_OkHibp())

    demo = next(c for c in checks if c.name == "demo mode")
    assert demo.blocks_a_scan
    assert "synthetic" in demo.detail
