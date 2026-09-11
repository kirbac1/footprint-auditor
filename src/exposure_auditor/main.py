import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx2
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .api import auth, breaches, findings, identifiers, meta, remediation, scans
from .config import Settings, get_settings
from .crypto import FieldCipher, configure_cipher
from .db import create_tables, make_engine, make_sessionmaker
from .notify import AwsCodeSender, CodeSender, ConsoleCodeSender
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


def _bedrock_client(settings: Settings):
    # The client resolves credentials lazily, so without this check a missing
    # credential only surfaces mid-scan as a bare RuntimeError. Checking here
    # turns it into an immediate 503 on POST /scan instead.
    try:
        import boto3

        if boto3.Session().get_credentials() is None:
            log.warning("no AWS credentials found; scans are disabled")
            return None
        from anthropic import AsyncAnthropicBedrockMantle

        return AsyncAnthropicBedrockMantle(aws_region=settings.bedrock_region)
    except Exception as exc:
        log.warning("Bedrock client unavailable (%s); scans are disabled", type(exc).__name__)
        return None


def _web_dist(settings: Settings) -> Path | None:
    path = Path(settings.web_dist) if settings.web_dist else Path(__file__).resolve().parents[2] / "web" / "dist"
    return path if (path / "index.html").is_file() else None


def create_app(
    settings: Settings | None = None,
    *,
    llm: Any = _DEFAULT,
    search: SearchProvider | None = _DEFAULT,
    reverse_image: ReverseImageProvider | None = None,
    sender: CodeSender | None = None,
    http: httpx2.AsyncClient | None = None,
) -> FastAPI:
    """Build the app. Keyword overrides exist so tests can swap in fakes."""
    settings = settings or get_settings()
    cipher = FieldCipher(
        settings.field_encryption_key.get_secret_value(), settings.blind_index_key.get_secret_value()
    )
    configure_cipher(cipher)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        if settings.env != "prod":
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
            llm_client = _bedrock_client(settings)

        if sender is not None:
            code_sender = sender
        elif settings.verification_delivery == "aws":
            code_sender = AwsCodeSender(settings.bedrock_region, settings.ses_sender)
        else:
            code_sender = ConsoleCodeSender()
        app.state.services = Services(
            settings=settings,
            cipher=cipher,
            sessionmaker=make_sessionmaker(engine),
            http=client,
            hibp=HibpClient(
                client, settings.hibp_api_key.get_secret_value() if settings.hibp_api_key else None
            ),
            search=search_provider,
            reverse_image=reverse_image,
            llm=llm_client,
            brokers=BrokerRegistry.load(),
            sender=code_sender,
            limiter=RateLimiter(),
        )
        try:
            yield
        finally:
            if http is None:
                await client.aclose()
            await engine.dispose()

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
