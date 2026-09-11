"""Check that each opt-out URL in the broker registry still resolves.

Read-only: it fetches the page and prints the status and final URL. It never
submits a form. A 403 often just means the site blocks non-browser clients;
open those by hand. A 200 means the page exists, not that the procedure is
unchanged, so confirm the steps before setting last_verified.

    uv run python scripts/check_brokers.py
"""

import asyncio

import httpx2

from exposure_auditor.tools.brokers import BrokerRegistry


async def main() -> None:
    headers = {"user-agent": "exposure-auditor-registry-check/0.1"}
    async with httpx2.AsyncClient(timeout=15.0, follow_redirects=True, headers=headers) as client:
        for broker in BrokerRegistry.load().all():
            if not broker.opt_out_url:
                print(f"{broker.id:18} -    no URL (method: {broker.method})")
                continue
            try:
                r = await client.get(broker.opt_out_url)
                moved = "" if str(r.url) == broker.opt_out_url else f" -> {r.url}"
                print(f"{broker.id:18} {r.status_code}  {broker.opt_out_url}{moved}")
            except httpx2.HTTPError as exc:
                print(f"{broker.id:18} ERR  {broker.opt_out_url} ({type(exc).__name__})")


if __name__ == "__main__":
    asyncio.run(main())
