"""exposure-auditor: serve, migrate, worker, check, stats, set-password (and eval)."""

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

    password = sub.add_parser(
        "set-password", help="set an account's password from the server (asks for it; never on the command line)"
    )
    password.add_argument("email", help="the account's email address")

    evals = sub.add_parser("eval", help="run the agent eval suite (see evals/README.md)")
    evals.add_argument("--provider", default="demo", help="demo (scripted), or bedrock, foundry, anthropic")
    evals.add_argument("--cases", default=None, help="path to the eval cases (default: evals/cases)")
    evals.add_argument("--report", default=None, help="write the JSON report here")
    evals.add_argument("--gate", action="store_true", help="exit non-zero if evals/thresholds.yaml isn't met")
    evals.add_argument("--language", default="en", choices=["en", "fi"], help="the language the agent answers in")
    evals.add_argument(
        "--repeat", type=int, default=1, metavar="N",
        help="run the suite N times and report the mean with the range; a model's answers vary",
    )

    args = parser.parse_args(argv)
    {
        "serve": _serve,
        "migrate": _migrate,
        "worker": _worker,
        "stats": _stats,
        "check": _check,
        "set-password": _set_password,
        "eval": _eval,
    }[args.cmd](args)


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


def _set_password(args: argparse.Namespace) -> None:
    """Break-glass for an operator at the machine: no email, no token, no link.

    The password is read from the terminal, never from a shell argument, so it
    stays out of the shell history and the process list. This is not the user
    flow -- that has to prove control of a verified address -- and every use
    is written to the audit log.
    """
    import getpass
    import sys

    from sqlalchemy import select

    from .audit import record
    from .config import get_settings
    from .identifiers import InvalidIdentifier, normalize
    from .main import service_context
    from .models import User
    from .security import hash_password

    settings = get_settings()

    async def go() -> str:
        async with service_context(settings, llm=None, search=None) as services:
            async with services.sessionmaker() as session:
                try:
                    # The same normalization the login path uses, or the blind
                    # index won't match the row it wrote.
                    address = normalize("email", args.email)
                except InvalidIdentifier as exc:
                    return f"Not an email address: {exc}"
                index = services.cipher.blind_index("user-email", address)
                user = (await session.scalars(select(User).where(User.email_index == index))).first()
                if user is None:
                    return f"No account for {args.email}."
                new = getpass.getpass("New password (at least 12 characters): ")
                if len(new) < 12:
                    return "Password too short: at least 12 characters."
                if new != getpass.getpass("Repeat it: "):
                    return "Those didn't match; nothing changed."
                user.password_hash = hash_password(new)
                record(session, user.id, "password.set_by_operator", "user", user.id)
                await session.commit()
                return f"Password set for {args.email}. Existing sign-ins stay valid until their token expires."

    message = asyncio.run(go())
    print(message)
    sys.exit(0 if message.startswith("Password set") else 1)


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
