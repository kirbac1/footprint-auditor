from dataclasses import dataclass
from typing import Any

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .crypto import FieldCipher
from .notify import CodeSender
from .ratelimit import RateLimiter
from .tools.brokers import BrokerRegistry
from .tools.hibp import HibpClient
from .tools.reverse_image import ReverseImageProvider
from .tools.search import SearchProvider


@dataclass
class Services:
    """Everything a request handler or background job needs, built once per app."""

    settings: Settings
    cipher: FieldCipher
    sessionmaker: async_sessionmaker[AsyncSession]
    http: httpx2.AsyncClient
    hibp: HibpClient
    search: SearchProvider | None
    reverse_image: ReverseImageProvider | None
    llm: Any  # AsyncAnthropicBedrockMantle, or a test double with .messages.create
    brokers: BrokerRegistry
    sender: CodeSender
    limiter: RateLimiter
