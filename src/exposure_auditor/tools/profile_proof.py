"""Username ownership proof: a one-time code in the account's public bio.

Only platforms with a public, unauthenticated profile API are supported, so a
check is one JSON request to a fixed host: no scraping, no redirects
followed, and the handle only ever lands in a URL path or query parameter,
never in the host. Instagram, X, TikTok and LinkedIn don't offer such an API,
so usernames there can't be proven this way yet.
"""

import secrets
from dataclasses import dataclass
from urllib.parse import quote

import httpx2


@dataclass(frozen=True)
class Platform:
    id: str
    label: str
    api_url: str  # {handle} is URL-encoded before substitution
    bio_field: str
    profile_url: str
    where: str


PLATFORMS: dict[str, Platform] = {
    "github": Platform(
        id="github",
        label="GitHub",
        api_url="https://api.github.com/users/{handle}",
        bio_field="bio",
        profile_url="https://github.com/{handle}",
        where="the Bio field of your GitHub profile",
    ),
    "bluesky": Platform(
        id="bluesky",
        label="Bluesky",
        api_url="https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor={handle}",
        bio_field="description",
        profile_url="https://bsky.app/profile/{handle}",
        where="your Bluesky profile description",
    ),
}


class ProofError(RuntimeError):
    pass


class ProfileNotFound(ProofError):
    pass


def new_code() -> str:
    # Random per challenge: someone else's account can't reuse a code the
    # real owner once posted, and nobody can guess one in advance.
    return f"footprint-verify-{secrets.token_hex(4)}"


async def fetch_bio(http: httpx2.AsyncClient, platform_id: str, handle: str) -> str:
    platform = PLATFORMS[platform_id]
    url = platform.api_url.format(handle=quote(handle, safe=""))
    r = await http.get(url, headers={"Accept": "application/json", "User-Agent": "exposure-auditor/0.1"})
    if r.status_code in (400, 404):
        raise ProfileNotFound(f"No {platform.label} account is called {handle}.")
    if r.status_code in (403, 429):
        raise ProofError(f"{platform.label} is limiting profile lookups right now. Try again in a few minutes.")
    if r.status_code != 200:
        raise ProofError(f"{platform.label} returned HTTP {r.status_code}.")
    return str(r.json().get(platform.bio_field) or "")
