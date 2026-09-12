"""Model providers.

The agent only calls `.messages.create(...)`. This wraps whichever client
serves Claude here: Amazon Bedrock, Microsoft Foundry or the Anthropic API.
Where the provider supports it, it also turns on server-side refusal
fallbacks: Claude Opus 5's safety classifiers can occasionally decline a
request, and `fallbacks="default"` re-runs it on Anthropic's recommended
fallback model inside the same call. Bedrock and Foundry don't offer that, so
there a refusal ends the scan as "refused".
"""

import logging
import os
from typing import Any

import httpx2

from .config import Settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLM:
    def __init__(self, client: Any, provider: str, server_fallbacks: bool) -> None:
        self._client = client
        self.provider = provider
        self._server_fallbacks = server_fallbacks
        self.messages = self

    async def create(self, **kwargs: Any) -> Any:
        if self._server_fallbacks:
            return await self._client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return await self._client.messages.create(**kwargs)


def make_llm(settings: Settings) -> LLM | None:
    """Build the configured client, or None (scans disabled) if it can't be used.

    Credentials are checked up front because the clients resolve them
    lazily: without this, a missing credential only surfaces mid-scan.
    """
    provider = settings.llm_provider
    try:
        if provider in ("ollama", "openai"):
            from .openai_compat import OpenAICompatLLM

            base = settings.ollama_host if provider == "ollama" else settings.openai_base_url
            if not base:
                log.warning("EA_OPENAI_BASE_URL is not set; scans are disabled")
                return None
            if provider == "openai" and not settings.model_id:
                log.warning("EA_MODEL_ID is required with EA_LLM_PROVIDER=openai; scans are disabled")
                return None
            key = (settings.openai_api_key.get_secret_value() if settings.openai_api_key else None) or None
            return OpenAICompatLLM(
                httpx2.AsyncClient(timeout=settings.llm_timeout_seconds), base, key, provider
            )

        if provider == "bedrock":
            import boto3

            if boto3.Session().get_credentials() is None:
                log.warning("no AWS credentials found; scans are disabled")
                return None
            from anthropic import AsyncAnthropicBedrockMantle

            return LLM(AsyncAnthropicBedrockMantle(aws_region=settings.bedrock_region), provider, False)

        if provider == "foundry":
            if not settings.foundry_resource:
                log.warning("EA_FOUNDRY_RESOURCE is not set; scans are disabled")
                return None
            from anthropic import AsyncAnthropicFoundry

            key = settings.foundry_api_key.get_secret_value() if settings.foundry_api_key else None
            return LLM(AsyncAnthropicFoundry(resource=settings.foundry_resource, api_key=key), provider, False)

        # An empty value (say, an unset CI secret) means "no key", not a blank one.
        key = (settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None) or None
        if key is None and not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            log.warning("no Anthropic API key found; scans are disabled")
            return None
        from anthropic import AsyncAnthropic

        return LLM(AsyncAnthropic(api_key=key) if key else AsyncAnthropic(), provider, True)
    except Exception as exc:
        log.warning("%s client unavailable (%s); scans are disabled", provider, type(exc).__name__)
        return None
