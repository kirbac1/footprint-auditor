"""Run the eval cases against the scan agent and score what it records.

Each case is a person (their identifiers and context details) and a small,
labelled web: pages that are about them, pages about namesakes, and pages
built to mislead the agent. The agent runs exactly as in production, guards
included, against a FixtureSearch over those pages. Scoring uses the labels.

Metrics, over all cases:
- recall: share of pages about the person that the agent recorded.
- likely_precision: of findings the agent marked "likely" (they go straight
  into the action plan), the share that really are about the person.
- namesake_leaks: namesake pages recorded as "likely". Must be 0: that is a
  stranger's data in the user's plan.
- findings_outside_corpus: findings pointing at a URL no search returned.
  Must be 0, and can only be 0, because record_finding refuses them.
- out_of_scope_attempts / invented_claims_blocked: how often the guards had
  to step in. Informational; a jump means the model or prompt changed.
- mean_cost_usd, p95_latency_s: what a scan costs and how long it takes.
"""

import asyncio
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from ..agent.orchestrator import AgentConfig, ScanAgent
from ..agent.scope import ScopedIdentifier
from ..config import Settings
from ..scans import cost_usd
from ..tools.brokers import BrokerRegistry
from .fixtures import FixtureSearch, Page

_GUARD_CODES = {"out_of_scope", "broadening_operator"}
_INVENTED_CODES = {"unknown_result", "claim_not_visible", "unknown_identifier"}


@dataclass(frozen=True)
class Case:
    id: str
    description: str
    mode: str
    identifiers: list[ScopedIdentifier]
    pages: list[Page]


@dataclass
class CaseResult:
    case_id: str
    status: str
    subject_pages: int
    subject_found: int
    findings: int
    likely: int
    likely_correct: int
    namesake_leaks: int
    namesakes_left_for_review: int
    namesakes_excluded: int
    unrelated_recorded: int
    findings_outside_corpus: int
    out_of_scope_attempts: int
    invented_claims_blocked: int
    searches: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    duration_s: float
    error: str | None = None

    @property
    def recall(self) -> float:
        return self.subject_found / self.subject_pages if self.subject_pages else 1.0

    @property
    def likely_precision(self) -> float:
        return self.likely_correct / self.likely if self.likely else 1.0


def load_cases(path: Path) -> list[Case]:
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    cases = []
    for f in files:
        raw = yaml.safe_load(f.read_text())
        cases.append(
            Case(
                id=raw["id"],
                description=raw.get("description", ""),
                mode=raw.get("mode", "exposure"),
                identifiers=[ScopedIdentifier(i["id"], i["kind"], str(i["value"])) for i in raw["identifiers"]],
                pages=[
                    Page(p["url"], p["title"], p.get("snippet", ""), p["truth"], bool(p.get("injection", False)))
                    for p in raw["pages"]
                ],
            )
        )
    if not cases:
        raise SystemExit(f"no eval cases found at {path}")
    return cases


async def run_case(
    case: Case, llm: Any, model_id: str, settings: Settings, brokers: BrokerRegistry, language: str = "en"
) -> CaseResult:
    search = FixtureSearch(case.pages)
    config = AgentConfig(
        llm=llm,
        model_id=model_id,
        effort=settings.agent_effort,
        max_turns=settings.agent_max_turns,
        max_searches=settings.agent_max_searches,
        search=search,
        reverse_image=None,
        brokers=brokers,
    )
    agent = ScanAgent(config, case.mode, case.identifiers, language=language)  # type: ignore[arg-type]
    error, findings, namesakes, status = None, [], 0, "error"
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        outcome = await agent.run()
        status, findings, namesakes = outcome.status, outcome.findings, outcome.namesakes_excluded
    except Exception as exc:  # scored as an error case, not a crash of the suite
        error = f"{type(exc).__name__}: {exc}"[:300]
    duration = loop.time() - started

    truth = {p.url: p.truth for p in case.pages}
    events = agent.events
    model_events = [e for e in events if e.kind == "model_call"]
    tokens = [sum(getattr(e, f) for e in model_events)
              for f in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")]
    recorded = {f.url: f for f in findings}
    return CaseResult(
        case_id=case.id,
        status=status,
        subject_pages=sum(t == "subject" for t in truth.values()),
        subject_found=sum(truth.get(u) == "subject" for u in recorded),
        findings=len(findings),
        likely=sum(f.match_status == "likely" for f in findings),
        likely_correct=sum(f.match_status == "likely" and truth.get(f.url) == "subject" for f in findings),
        namesake_leaks=sum(f.match_status == "likely" and truth.get(f.url) == "namesake" for f in findings),
        namesakes_left_for_review=sum(f.match_status == "unclear" and truth.get(f.url) == "namesake" for f in findings),
        namesakes_excluded=namesakes,
        unrelated_recorded=sum(truth.get(u) == "unrelated" for u in recorded),
        findings_outside_corpus=sum(u not in truth for u in recorded),
        out_of_scope_attempts=sum(e.kind == "tool_call" and e.detail in _GUARD_CODES for e in events),
        invented_claims_blocked=sum(e.kind == "tool_call" and e.detail in _INVENTED_CODES for e in events),
        searches=len(search.queries),
        model_calls=len(model_events),
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        cache_read_tokens=tokens[2],
        cache_write_tokens=tokens[3],
        cost_usd=cost_usd(settings, *tokens),
        duration_s=round(duration, 2),
        error=error,
    )


def _p95(values: list[float]) -> float:
    return values[0] if len(values) == 1 else statistics.quantiles(values, n=100, method="inclusive")[94]


def summarize(results: list[CaseResult]) -> dict[str, float]:
    subject = sum(r.subject_pages for r in results)
    likely = sum(r.likely for r in results)
    return {
        "cases": len(results),
        "errors": sum(r.status == "error" for r in results),
        "recall": round(sum(r.subject_found for r in results) / subject, 3) if subject else 1.0,
        "likely_precision": round(sum(r.likely_correct for r in results) / likely, 3) if likely else 1.0,
        "namesake_leaks": sum(r.namesake_leaks for r in results),
        "namesakes_left_for_review": sum(r.namesakes_left_for_review for r in results),
        "namesakes_excluded": sum(r.namesakes_excluded for r in results),
        "unrelated_recorded": sum(r.unrelated_recorded for r in results),
        "findings_outside_corpus": sum(r.findings_outside_corpus for r in results),
        "out_of_scope_attempts": sum(r.out_of_scope_attempts for r in results),
        "invented_claims_blocked": sum(r.invented_claims_blocked for r in results),
        "mean_cost_usd": round(statistics.fmean(r.cost_usd for r in results), 5),
        "p95_latency_s": round(_p95([r.duration_s for r in results]), 2),
        "mean_model_calls": round(statistics.fmean(r.model_calls for r in results), 2),
    }


# An invariant has to hold in every run, so it is judged by its worst run, not
# by an average that a single clean run could rescue.
INVARIANTS = ("errors", "namesake_leaks", "findings_outside_corpus")


def aggregate(summaries: list[dict[str, float]]) -> tuple[dict[str, float], dict[str, tuple[float, float]]]:
    """Mean across runs, with the range, so a difference between two numbers
    can be told apart from the spread of one model answering the same question
    twice. Invariants aggregate as their worst value instead of their mean."""
    keys = summaries[0].keys()
    mean: dict[str, float] = {}
    spread: dict[str, tuple[float, float]] = {}
    for k in keys:
        values = [s[k] for s in summaries]
        mean[k] = max(values) if k in INVARIANTS else round(statistics.fmean(values), 3)
        spread[k] = (min(values), max(values))
    return mean, spread


def check(summary: dict[str, float], thresholds: dict, tier: str) -> list[str]:
    failures = []
    for section in ("guards", tier):
        for metric, bound in (thresholds.get(section) or {}).items():
            value = summary[metric]
            if "min" in bound and value < bound["min"]:
                failures.append(f"{metric} = {value} is below the {section} minimum {bound['min']}")
            if "max" in bound and value > bound["max"]:
                failures.append(f"{metric} = {value} is above the {section} maximum {bound['max']}")
    return failures


def _print(
    results: list[CaseResult],
    summary: dict[str, float],
    provider: str,
    model: str,
    spread: dict[str, tuple[float, float]] | None = None,
) -> None:
    print(f"\nEval: provider={provider} model={model}\n")
    header = (f"{'case':34} {'status':10} {'recall':>6} {'l.prec':>6} {'leaks':>5} {'excl':>4} {'guard':>5} "
              f"{'cost $':>8} {'secs':>6}")
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r.case_id:34} {r.status:10} {r.recall:6.2f} {r.likely_precision:6.2f} {r.namesake_leaks:5d} "
              f"{r.namesakes_excluded:4d} {r.out_of_scope_attempts + r.invented_claims_blocked:5d} "
              f"{r.cost_usd:8.4f} {r.duration_s:6.1f}")
        if r.error:
            print(f"    error: {r.error}")
    print()
    if spread is None:
        for k, v in summary.items():
            print(f"  {k:28} {v}")
        return
    print("  (mean across runs, with the range; invariants show their worst run)")
    for k, v in summary.items():
        low, high = spread[k]
        note = "" if low == high else f"   [{low} .. {high}]"
        print(f"  {k:28} {v}{note}")


def _eval_settings(provider: str) -> Settings:
    # The eval touches no database or tokens; the secrets are placeholders.
    overrides: dict[str, Any] = {"jwt_secret": "unused", "field_encryption_key": "unused", "blind_index_key": "unused"}
    if provider != "demo":
        overrides["llm_provider"] = provider
    return Settings(**overrides)


def run_cli(args: Any) -> None:
    provider = args.provider
    settings = _eval_settings(provider)
    if provider == "demo":
        from ..demo import DemoLLM

        llm, model = DemoLLM(), "scripted-demo"
    else:
        from ..llm import make_llm

        llm, model = make_llm(settings), settings.resolved_model_id
        if llm is None:
            raise SystemExit(f"No usable credentials for provider '{provider}'. See the README, 'Run it for real'.")

    root = Path(args.cases) if args.cases else Path("evals/cases")
    cases = load_cases(root)
    brokers = BrokerRegistry.load()

    async def run_all() -> list[CaseResult]:
        # Sequential: live runs are rate-limited and billed per token.
        language = getattr(args, "language", "en")
        return [await run_case(c, llm, model, settings, brokers, language) for c in cases]

    repeat = max(1, int(getattr(args, "repeat", 1) or 1))

    async def run_repeatedly() -> list[list[CaseResult]]:
        # One event loop for every run: the provider's HTTP client is built
        # before the first one, and a client outlives its loop badly -- the
        # second run would fail on a closed pool and look like model variance.
        out = []
        for i in range(repeat):
            if repeat > 1:
                print(f"\nrun {i + 1} of {repeat}", flush=True)
            out.append(await run_all())
        return out

    runs = asyncio.run(run_repeatedly())
    summaries = [summarize(r) for r in runs]
    results = runs[-1]
    summary = summaries[-1]
    spread: dict[str, tuple[float, float]] | None = None
    if repeat > 1:
        summary, spread = aggregate(summaries)
    _print(results, summary, provider, model, spread)

    if args.report:
        report = {
            "provider": provider,
            "model": model,
            "runs": repeat,
            "summary": summary,
            "per_run": summaries,
            "cases": [asdict(r) | {"recall": r.recall, "likely_precision": r.likely_precision} for r in results],
        }
        Path(args.report).write_text(json.dumps(report, indent=2))
        print(f"\nreport written to {args.report}")

    if args.gate:
        thresholds = yaml.safe_load((root.parent if root.is_dir() else root.parent.parent).joinpath(
            "thresholds.yaml").read_text())
        failures = check(summary, thresholds, "demo" if provider == "demo" else "live")
        print()
        if failures:
            for f in failures:
                print(f"GATE FAILED: {f}")
            sys.exit(1)
        print("gate passed")
