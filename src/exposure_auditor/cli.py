"""exposure-auditor: serve, migrate, worker, check, stats (and eval, see evals/)."""

import argparse
import asyncio
import statistics


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="exposure-auditor")
    parser.set_defaults(cmd="serve", host="127.0.0.1", port=8000, no_migrate=False)
    sub = parser.add_subparsers(dest="cmd")

    serve = sub.add_parser("serve", help="migrate the database, then run the API (the default)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--no-migrate", action="store_true", help="skip migrations (several API replicas)")

    migrate = sub.add_parser("migrate", help="apply database migrations")
    migrate.add_argument("--stamp", metavar="REVISION", help="mark an existing database as being at REVISION")

    sub.add_parser("worker", help="run queued scans (with EA_SCAN_EXECUTION=worker)")
    sub.add_parser("stats", help="latency and cost across finished scans")
    sub.add_parser("check", help="verify credentials and config before a real scan")

    evals = sub.add_parser("eval", help="run the agent eval suite (see evals/README.md)")
    evals.add_argument("--provider", default="demo", help="demo (scripted), or bedrock, foundry, anthropic")
    evals.add_argument("--cases", default=None, help="path to the eval cases (default: evals/cases)")
    evals.add_argument("--report", default=None, help="write the JSON report here")
    evals.add_argument("--gate", action="store_true", help="exit non-zero if evals/thresholds.yaml isn't met")

    args = parser.parse_args(argv)
    {"serve": _serve, "migrate": _migrate, "worker": _worker, "stats": _stats, "check": _check, "eval": _eval}[
        args.cmd
    ](args)


def _serve(args: argparse.Namespace) -> None:
    import uvicorn

    from . import migrations

    if not args.no_migrate:
        migrations.upgrade()
    uvicorn.run("exposure_auditor.main:create_app", factory=True, host=args.host, port=args.port)


def _migrate(args: argparse.Namespace) -> None:
    from . import migrations

    if args.stamp:
        migrations.stamp(args.stamp)
    else:
        migrations.upgrade()


def _worker(args: argparse.Namespace) -> None:
    import logging

    from .config import get_settings
    from .main import service_context
    from .worker import run_worker

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def go() -> None:
        async with service_context(get_settings()) as services:
            await run_worker(services)

    asyncio.run(go())


def _check(args: argparse.Namespace) -> None:
    import sys

    from .config import get_settings
    from .preflight import format_checks, run_checks

    checks = asyncio.run(run_checks(get_settings()))
    print(format_checks(checks))
    sys.exit(1 if any(c.blocks_a_scan for c in checks) else 0)


def _percentile(values: list[float], pct: int) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[pct - 1]


def _stats(args: argparse.Namespace) -> None:
    from sqlalchemy import select

    from .config import get_settings
    from .main import service_context
    from .models import Scan

    async def go() -> list:
        async with service_context(get_settings(), llm=None, search=None) as services:
            async with services.sessionmaker() as session:
                return (
                    await session.execute(
                        select(Scan.status, Scan.duration_ms, Scan.cost_usd, Scan.input_tokens, Scan.output_tokens,
                               Scan.cache_read_tokens, Scan.model_calls).where(Scan.duration_ms.is_not(None))
                    )
                ).all()

    rows = asyncio.run(go())
    if not rows:
        print("No finished scans yet.")
        return
    seconds = [r.duration_ms / 1000 for r in rows]
    costs = [r.cost_usd or 0.0 for r in rows]
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    print(f"scans            {len(rows)}  ({', '.join(f'{k} {v}' for k, v in sorted(by_status.items()))})")
    print(f"latency          p50 {_percentile(seconds, 50):.1f} s   p95 {_percentile(seconds, 95):.1f} s")
    print(f"cost per scan    mean ${statistics.fmean(costs):.4f}   p95 ${_percentile(costs, 95):.4f}   "
          f"total ${sum(costs):.2f}")
    print(f"model calls      mean {statistics.fmean(r.model_calls for r in rows):.1f}")
    print(f"tokens per scan  input {statistics.fmean(r.input_tokens for r in rows):,.0f}   "
          f"output {statistics.fmean(r.output_tokens for r in rows):,.0f}   "
          f"cache reads {statistics.fmean(r.cache_read_tokens for r in rows):,.0f}")


def _eval(args: argparse.Namespace) -> None:
    from .evals import run_cli

    run_cli(args)
