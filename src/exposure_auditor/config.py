from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The donate link goes on every page of a site people trust with their data;
# only allow PayPal, so a config typo can't send them somewhere else.
_DONATE_HOSTS = {"paypal.com", "www.paypal.com", "paypal.me", "www.paypal.me"}


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

    bedrock_region: str = "eu-central-1"
    model_id: str = "anthropic.claude-opus-5"
    agent_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    agent_max_turns: int = 24
    agent_max_searches: int = 40

    hibp_api_key: SecretStr | None = None
    brave_api_key: SecretStr | None = None

    verification_delivery: Literal["console", "aws"] = "console"
    ses_sender: str | None = None

    # Local UI work without AWS: scans run the real agent loop against a
    # scripted model and synthetic search results (see demo.py).
    demo_scans: bool = False
    # Built frontend (web/dist). Detected next to the source tree if unset.
    web_dist: str | None = None
    # PayPal donate link shown in the UI header; no button when unset.
    donate_url: str | None = None

    @field_validator("donate_url")
    @classmethod
    def _paypal_only(cls, v: str | None) -> str | None:
        if not v:
            return None
        parts = urlsplit(v)
        if parts.scheme != "https" or (parts.hostname or "") not in _DONATE_HOSTS:
            raise ValueError("EA_DONATE_URL must be an https:// link on paypal.com or paypal.me")
        return v

    rate_limit_per_minute: int = 30
    scans_per_day: int = 5
    max_attested_names: int = 3
    max_attested_usernames: int = 5
    max_attested_images: int = 5
    max_image_bytes: int = 4 * 1024 * 1024

    @model_validator(mode="after")
    def _prod_guards(self) -> "Settings":
        if self.env == "prod":
            if self.verification_delivery == "console":
                # The console sender writes codes to the log; in prod that would
                # let anyone with log access verify identifiers they don't own.
                raise ValueError("EA_VERIFICATION_DELIVERY=console is not allowed in prod")
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
