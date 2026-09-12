import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import tracing
from .api import auth, breaches, findings, identifiers, meta, remediation, scans
from .config import Settings, get_settings
from .crypto import FieldCipher, configure_cipher
from .db import create_tables, make_engine, make_sessionmaker
from .llm import make_llm
from .notify import AwsCodeSender, CodeSender, ConsoleCodeSender, OutboxCodeSender
from .ratelimit import RateLimiter
from .services import Services
from .tools.brokers import BrokerRegistry
from .tools.hibp import HibpClient
from .tools.reverse_image import ReverseImageProvider
from .tools.search import BraveSearch, SearchProvider

log = logging.getLogger(__name__)
_DEFAULT: Any = object()

# The frontend is static Vite output with no inline scripts or styles, so the
# policy can be strict. Swagger at /docs loads from a CDN and doesn't get it.
SPA_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)


def _web_dist(settings: Settings) -> Path | None:
    path = Path(settings.web_dist) if settings.web_dist else Path(__file__).resolve().parents[2] / "web" / "dist"
    return path if (path / "index.html").is_file() else None


def _code_sender(settings: Settings) -> CodeSender:
    if settings.verification_delivery == "aws":
        return AwsCodeSender(settings.bedrock_region, settings.ses_sender)
    if settings.verification_delivery == "outbox":
        return OutboxCodeSender(settings.outbox_path)
    return ConsoleCodeSender()


@asynccontextmanager
async def service_context(
    settings: Settings,
    *,
    llm: Any = _DEFAULT,
    search: SearchProvider | None = _DEFAULT,
    reverse_image: ReverseImageProvider | None = None,
    sender: CodeSender | None = None,
    http: httpx2.AsyncClient | None = None,
) -> AsyncIterator[Services]:
    """Everything the API, the worker and the eval runner need. Keyword
    overrides exist so tests can swap in fakes."""
    cipher = FieldCipher(
        settings.field_encryption_key.get_secret_value(), settings.blind_index_key.get_secret_value()
    )
    configure_cipher(cipher)
    engine = make_engine(settings.database_url)
    if settings.env == "test":
        # Tests build a throwaway schema directly. Everywhere else the schema
        # comes from migrations: `exposure-auditor migrate`, which `serve` runs first.
        await create_tables(engine)
    client = http or httpx2.AsyncClient(timeout=20.0)

    if settings.demo_scans:
        from .demo import DemoLLM, DemoSearch

        log.warning("EA_DEMO_SCANS is on: scans use a scripted model and synthetic search results")
    if search is not _DEFAULT:
        search_provider = search
    elif settings.demo_scans:
        search_provider = DemoSearch()
    elif settings.brave_api_key:
        search_provider = BraveSearch(client, settings.brave_api_key.get_secret_value())
    else:
        search_provider = None
    if llm is not _DEFAULT:
        llm_client = llm
    elif settings.demo_scans:
        llm_client = DemoLLM()
    else:
        llm_client = make_llm(settings)

    sessionmaker = make_sessionmaker(engine)
    services = Services(
        settings=settings,
        cipher=cipher,
        sessionmaker=sessionmaker,
        http=client,
        hibp=HibpClient(client, settings.hibp_api_key.get_secret_value() if settings.hibp_api_key else None),
        search=search_provider,
        reverse_image=reverse_image,
        llm=llm_client,
        brokers=BrokerRegistry.load(),
        sender=sender or _code_sender(settings),
        limiter=RateLimiter(sessionmaker, engine.dialect.name),
    )
    try:
        yield services
    finally:
        if http is None:
            await client.aclose()
        await engine.dispose()


def create_app(
    settings: Settings | None = None,
    *,
    llm: Any = _DEFAULT,
    search: SearchProvider | None = _DEFAULT,
    reverse_image: ReverseImageProvider | None = None,
    sender: CodeSender | None = None,
    http: httpx2.AsyncClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if settings.otel_enabled:
        tracing.configure()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with service_context(
            settings, llm=llm, search=search, reverse_image=reverse_image, sender=sender, http=http
        ) as services:
            app.state.services = services
            yield

    app = FastAPI(
        title="Personal Data Exposure Auditor",
        version="0.1.0",
        description=(
            "Finds where your own data is exposed and turns it into a remediation plan. "
            "It does not delete anything on your behalf."
        ),
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # The UI links out to broker and profile pages; don't tell them where from.
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    for module in (auth, identifiers, scans, findings, breaches, remediation, meta):
        app.include_router(module.router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"status": "ok"}

    dist = _web_dist(settings)
    if dist is not None:
        if (dist / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/", include_in_schema=False)
        async def spa() -> HTMLResponse:
            return HTMLResponse(
                (dist / "index.html").read_text(),
                headers={"Content-Security-Policy": SPA_CSP, "Cache-Control": "no-store"},
            )

    return app
