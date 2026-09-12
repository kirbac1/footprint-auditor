"""Pre-flight: does this deployment have everything a real scan needs?

Worth running before pointing real credentials at real data. Each dependency
gets one cheap call, so a missing key, a wrong region or a model you don't have
access to fails here in a second rather than halfway through a scan that has
already spent money and used up a daily slot.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx2
from sqlalchemy import text

from .config import Settings
from .db import make_engine
from .llm import make_llm
from .tools.hibp import HibpClient, HibpError
from .tools.search import BraveSearch, SearchError

log = logging.getLogger(__name__)

# One in-scope-looking query against a domain that is meant for examples.
_PROBE_QUERY = "example.com"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    @property
    def blocks_a_scan(self) -> bool:
        return self.required and not self.ok


async def _database(settings: Settings) -> Check:
    engine = make_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            rev = (await conn.execute(text("select version_num from alembic_version"))).scalar_one_or_none()
        if rev is None:
            return Check("database", False, "reachable, but no migrations applied: run `exposure-auditor migrate`")
        return Check("database", True, f"reachable, at revision {rev}")
    except Exception as exc:
        return Check("database", False, f"{type(exc).__name__}: {exc}")
    finally:
        await engine.dispose()


async def _model(settings: Settings, llm: object | None) -> Check:
    client = llm if llm is not None else make_llm(settings)
    if client is None:
        return Check("model", False, f"no usable credentials for EA_LLM_PROVIDER={settings.llm_provider}")
    try:
        response = await client.messages.create(  # type: ignore[attr-defined]
            model=settings.resolved_model_id,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with the word ready."}],
        )
    except Exception as exc:
        return Check("model", False, f"{settings.llm_provider}: {type(exc).__name__}: {exc}")
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "output_tokens", 0) if usage else 0
    return Check("model", True, f"{settings.llm_provider} answered as {settings.resolved_model_id} ({tokens} tokens)")


async def _search(settings: Settings, http: httpx2.AsyncClient, search: object | None) -> Check:
    provider = search
    if provider is None:
        if not settings.brave_api_key:
            return Check("web search", False, "EA_BRAVE_API_KEY is not set; scans cannot search")
        provider = BraveSearch(http, settings.brave_api_key.get_secret_value())
    try:
        results = await provider.search(_PROBE_QUERY, count=1)  # type: ignore[attr-defined]
    except SearchError as exc:
        return Check("web search", False, str(exc))
    except Exception as exc:
        return Check("web search", False, f"{type(exc).__name__}: {exc}")
    pace = settings.search_min_interval_ms
    return Check("web search", True, f"{len(results)} result(s) for a probe query, paced at {pace} ms between calls")


async def _breaches(settings: Settings, http: httpx2.AsyncClient, hibp: object | None) -> Check:
    client = hibp or HibpClient(http, settings.hibp_api_key.get_secret_value() if settings.hibp_api_key else None)
    try:
        await client.password_range("00000")  # type: ignore[attr-defined]
    except HibpError as exc:
        return Check("breach data", False, f"password range check failed: {exc}", required=False)
    if not settings.hibp_api_key:
        return Check(
            "breach data",
            True,
            "password checks work; EA_HIBP_API_KEY is unset, so email breach lookups are off",
            required=False,
        )
    return Check("breach data", True, "password checks work and an email lookup key is configured", required=False)


def _configuration(settings: Settings) -> list[Check]:
    ceiling = (
        f"ceiling ${settings.max_scan_cost_usd:.2f} per scan" if settings.max_scan_cost_usd else "no cost ceiling"
    )
    out = [
        Check(
            "scan budget",
            True,
            f"{settings.agent_max_turns} turns, {settings.agent_max_searches} searches, {ceiling}",
            required=False,
        )
    ]
    if settings.demo_scans:
        out.append(Check("demo mode", False, "EA_DEMO_SCANS is on: findings are synthetic. Unset it for a real scan"))
    if settings.scan_execution == "worker":
        out.append(
            Check("execution", True, "scans are queued; `exposure-auditor worker` has to be running", required=False)
        )
    return out


async def run_checks(
    settings: Settings,
    *,
    llm: object | None = None,
    search: object | None = None,
    hibp: object | None = None,
    http: httpx2.AsyncClient | None = None,
) -> list[Check]:
    client = http or httpx2.AsyncClient(timeout=20.0)
    try:
        checks = [await _database(settings)]
        checks.extend(
            await asyncio.gather(
                _model(settings, llm),
                _search(settings, client, search),
                _breaches(settings, client, hibp),
            )
        )
        return checks + _configuration(settings)
    finally:
        if http is None:
            await client.aclose()


def format_checks(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [f"{'ok ' if c.ok else 'FAIL' if c.required else 'off'} {c.name.ljust(width)}  {c.detail}" for c in checks]
    blockers = [c for c in checks if c.blocks_a_scan]
    lines.append("")
    lines.append(
        "Ready for a real scan."
        if not blockers
        else "Not ready: " + ", ".join(c.name for c in blockers) + "."
    )
    return "\n".join(lines)
