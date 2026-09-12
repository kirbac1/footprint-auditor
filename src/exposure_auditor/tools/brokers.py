"""Registry of data brokers and people-search sites with their opt-out routes."""

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from urllib.parse import urlsplit

import yaml


@dataclass(frozen=True)
class Broker:
    id: str
    name: str
    domains: tuple[str, ...]
    jurisdictions: tuple[str, ...]
    method: str  # web_form | email | letter | operator
    opt_out_url: str | None
    privacy_email: str | None
    requires_id_verification: bool
    legal_bases: tuple[str, ...]  # gdpr | ccpa
    notes: str
    last_verified: str | None
    notes_fi: str = ""


class BrokerRegistry:
    def __init__(self, brokers: list[Broker]) -> None:
        self._by_id = {b.id: b for b in brokers}

    @classmethod
    def load(cls, path: Path | None = None) -> "BrokerRegistry":
        if path is None:
            text = resources.files("exposure_auditor.data").joinpath("brokers.yaml").read_text()
        else:
            text = path.read_text()
        raw = yaml.safe_load(text)["brokers"]
        return cls([
            Broker(
                id=b["id"],
                name=b["name"],
                domains=tuple(b["domains"]),
                jurisdictions=tuple(b.get("jurisdictions", [])),
                method=b["method"],
                opt_out_url=b.get("opt_out_url"),
                privacy_email=b.get("privacy_email"),
                requires_id_verification=bool(b.get("requires_id_verification", False)),
                legal_bases=tuple(b.get("legal_bases", [])),
                notes=b.get("notes", ""),
                last_verified=b.get("last_verified"),
                notes_fi=b.get("notes_fi", ""),
            )
            for b in raw
        ])

    def all(self) -> list[Broker]:
        return list(self._by_id.values())

    def get(self, broker_id: str) -> Broker | None:
        return self._by_id.get(broker_id)

    def match_url(self, url: str) -> Broker | None:
        host = (urlsplit(url).hostname or "").lower()
        for broker in self._by_id.values():
            if any(host == d or host.endswith("." + d) for d in broker.domains):
                return broker
        return None
