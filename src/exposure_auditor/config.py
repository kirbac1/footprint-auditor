from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The donate link goes on every page of a site people trust with their data;
# only allow PayPal, so a config typo can't send them somewhere else.
_DONATE_HOSTS = {"paypal.com", "www.paypal.com", "paypal.me", "www.paypal.me"}

_DEFAULT_MODELS = {
    "bedrock": "anthropic.claude-opus-5",
    "foundry": "claude-opus-5",
    "anthropic": "claude-opus-5",
    # A mixture-of-experts model small enough to run on a laptop: the scan
    # never leaves the machine, which matters for a tool that handles the
    # user's own identifiers. Set EA_MODEL_ID to try another local model.
    "ollama": "qwen3:30b-a3b-instruct-2507-q4_K_M",
    # No sensible default: whatever the endpoint in EA_OPENAI_BASE_URL serves.
    "openai": "",
}


class Settings(BaseSettings):
    """Runtime configuration, read from EA_* environment variables.

    In production the secrets are injected by the ECS task definition from
    Secrets Manager, so nothing here reads Secrets Manager directly.
    """

    model_config = SettingsConfigDict(env_prefix="EA_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite+aiosqlite:///./exposure_auditor.db"

    jwt_secret: SecretStr
    jwt_ttl_minutes: int = 30

    # Fernet key for encrypting PII columns, and a separate HMAC key for the
    # blind index that lets us look rows up without decrypting them.
    field_encryption_key: SecretStr
    blind_index_key: SecretStr

    # All three providers serve Claude through the Anthropic SDK; the agent
    # code is identical, only the client differs (see llm.py).
    llm_provider: Literal["bedrock", "foundry", "anthropic", "ollama", "openai"] = "bedrock"
    model_id: str | None = None  # defaults per provider, see resolved_model_id
    bedrock_region: str = "eu-central-1"
    foundry_resource: str | None = None
    foundry_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    # ollama: a model running on this machine, nothing leaves it.
    ollama_host: str = "http://127.0.0.1:11434/v1"
    # openai: any endpoint speaking the OpenAI chat-completions API, e.g.
    # https://api.mistral.ai/v1 or https://api.openai.com/v1.
    openai_base_url: str | None = None
    openai_api_key: SecretStr | None = None
    # A local model is slower per turn than a hosted one; a scan is many turns.
    llm_timeout_seconds: float = 300.0
    agent_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    agent_max_turns: int = 24
    agent_max_searches: int = 40
    # USD per million tokens, for the cost shown on each scan. The defaults
    # are Claude Opus 5's first-party list price; Bedrock and Foundry price
    # separately, so set these to what you are actually billed.
    price_input_per_mtok: float = 5.0
    price_output_per_mtok: float = 25.0
    # A ceiling on the estimated spend of a single scan. The agent stops and
    # summarizes what it has when the running total passes this, so a loop that
    # goes wrong costs a known amount. None removes the ceiling.
    max_scan_cost_usd: float | None = 1.0

    hibp_api_key: SecretStr | None = None
    # Reverse-image search for the impersonation check. TinEye matches copies
    # of the photo, not faces; see tools/reverse_image.py for why that matters.
    tineye_api_key: SecretStr | None = None
    tineye_base_url: str = "https://api.tineye.com/rest"
    brave_api_key: SecretStr | None = None
    # Brave's free tier allows one query per second and the agent issues tool
    # calls in parallel, so searches are paced and rate-limit replies retried.
    search_min_interval_ms: int = 1100
    search_max_retries: int = 2

    # console and outbox are for local work and tests only; prod refuses both.
    verification_delivery: Literal["console", "outbox", "aws"] = "console"
    ses_sender: str | None = None
    outbox_path: str = "outbox.jsonl"

    # inline: scans run as background tasks in the API process (dev, tests).
    # worker: the API only queues them; `exposure-auditor worker` runs them.
    scan_execution: Literal["inline", "worker"] = "inline"
    worker_poll_seconds: float = 2.0
    # Export scan traces as OpenTelemetry spans; the exporter itself is
    # configured with the standard OTEL_EXPORTER_OTLP_* variables.
    otel_enabled: bool = False

    # Local UI work without a model or search key: scans run the real agent
    # loop against a scripted model and synthetic results (see demo.py).
    demo_scans: bool = False
    # Force the scripted model even when a provider is configured. The
    # end-to-end tests need a scan that is instant and identical every run.
    demo_scripted_model: bool = False
    # Built frontend (web/dist). Detected next to the source tree if unset.
    web_dist: str | None = None
    # PayPal donate link shown in the UI header; no button when unset.
    donate_url: str | None = None

    rate_limit_per_minute: int = 30
    scans_per_day: int = 5
    # Across every account on this deployment. Per-account limits do not
    # protect a public instance: anyone can make another account. None = no cap.
    scans_per_day_total: int | None = None
    max_attested_names: int = 3
    max_attested_usernames: int = 5
    max_attested_images: int = 5
    max_image_bytes: int = 4 * 1024 * 1024
    # Usernames are only searched once proven with a code in a public bio.
    # Turning this on lets merely attested usernames into scans again.
    allow_unproven_usernames: bool = False

    @property
    def resolved_model_id(self) -> str:
        return self.model_id or _DEFAULT_MODELS[self.llm_provider]

    @field_validator("donate_url")
    @classmethod
    def _paypal_only(cls, v: str | None) -> str | None:
        if not v:
            return None
        parts = urlsplit(v)
        if parts.scheme != "https" or (parts.hostname or "") not in _DONATE_HOSTS:
            raise ValueError("EA_DONATE_URL must be an https:// link on paypal.com or paypal.me")
        return v

    @model_validator(mode="after")
    def _prod_guards(self) -> "Settings":
        if self.env == "prod":
            if self.verification_delivery in ("console", "outbox"):
                # Both write codes somewhere readable; in prod that would let
                # anyone with log or disk access verify identifiers they don't own.
                raise ValueError(f"EA_VERIFICATION_DELIVERY={self.verification_delivery} is not allowed in prod")
            if self.database_url.startswith("sqlite"):
                raise ValueError("prod requires a Postgres EA_DATABASE_URL")
            if self.demo_scans:
                raise ValueError("EA_DEMO_SCANS would show users synthetic findings; not allowed in prod")
        if self.verification_delivery == "aws" and not self.ses_sender:
            raise ValueError("EA_SES_SENDER is required when EA_VERIFICATION_DELIVERY=aws")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
