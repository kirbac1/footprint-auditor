"""Have I Been Pwned client.

Two very different privacy properties:

* breachedaccount sends the email address to HIBP. We only ever call it for
  emails the account holder has verified they control.
* Pwned Passwords is k-anonymous: only the first 5 hex chars of the SHA-1
  leave the client. Our endpoint accepts exactly that prefix, so a plaintext
  password or a full hash never reaches this service at all.
"""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx2

API = "https://haveibeenpwned.com/api/v3"
RANGE_API = "https://api.pwnedpasswords.com/range/"
_PREFIX = re.compile(r"^[0-9A-F]{5}$")


class HibpError(RuntimeError):
    pass


class HibpNotConfigured(HibpError):
    pass


@dataclass(frozen=True)
class Breach:
    name: str
    title: str
    domain: str
    breach_date: str
    data_classes: tuple[str, ...]
    is_verified: bool


class HibpClient:
    def __init__(self, http: httpx2.AsyncClient, api_key: str | None, user_agent: str = "exposure-auditor/0.1"):
        self._http = http
        self._api_key = api_key
        self._ua = user_agent

    async def breaches_for_account(self, email: str) -> list[Breach]:
        if not self._api_key:
            raise HibpNotConfigured("EA_HIBP_API_KEY is not set")
        url = f"{API}/breachedaccount/{quote(email, safe='')}"
        headers = {"hibp-api-key": self._api_key, "user-agent": self._ua}
        for attempt in range(2):
            r = await self._http.get(url, params={"truncateResponse": "false"}, headers=headers)
            if r.status_code == 429 and attempt == 0:
                wait = float(r.headers.get("retry-after", "2"))
                if wait <= 10:
                    await asyncio.sleep(wait)
                    continue
            break
        if r.status_code == 404:
            return []
        if r.status_code in (401, 403):
            raise HibpError("HIBP rejected the API key")
        if r.status_code == 429:
            raise HibpError("HIBP rate limit exceeded; try again later")
        if r.status_code != 200:
            raise HibpError(f"HIBP returned HTTP {r.status_code}")
        return [
            Breach(
                name=b["Name"],
                title=b.get("Title") or b["Name"],
                domain=b.get("Domain") or "",
                breach_date=b.get("BreachDate") or "",
                data_classes=tuple(b.get("DataClasses") or ()),
                is_verified=bool(b.get("IsVerified", True)),
            )
            for b in r.json()
        ]

    async def password_range(self, prefix: str) -> list[tuple[str, int]]:
        prefix = prefix.upper()
        if not _PREFIX.match(prefix):
            raise ValueError("prefix must be exactly 5 hex characters of a SHA-1 hash")
        r = await self._http.get(
            RANGE_API + prefix, headers={"Add-Padding": "true", "user-agent": self._ua}
        )
        if r.status_code != 200:
            raise HibpError(f"Pwned Passwords returned HTTP {r.status_code}")
        out: list[tuple[str, int]] = []
        for line in r.text.splitlines():
            suffix, _, count = line.strip().partition(":")
            # Padding rows carry a count of 0; they exist to hide the response
            # size on the wire and mean nothing to the caller.
            if count and int(count) > 0:
                out.append((suffix, int(count)))
        return out
