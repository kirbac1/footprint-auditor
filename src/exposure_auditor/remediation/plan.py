"""Turn scan findings and breach hits into a prioritized list of things to do.

Pure and deterministic: same inputs, same plan. The persistence layer
(remediation/service.py) upserts these by dedupe_key so the user's progress
on an item survives a rebuild.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..models import BreachHit, Finding
from ..tools.brokers import BrokerRegistry
from .letters import letter_for

CRITICAL, HIGH, MEDIUM, LOW = 0, 1, 2, 3
JURISDICTIONS = ("EU", "FI", "US-CA", "US", "OTHER")

_SENSITIVE_CLASSES = {
    "Security questions and answers",
    "Auth tokens",
    "Credit cards",
    "Partial credit card data",
    "Bank account numbers",
    "Government issued IDs",
    "Passport numbers",
    "Social security numbers",
}


@dataclass(frozen=True)
class PlannedItem:
    dedupe_key: str
    source_type: str
    source_id: str | None
    action_type: str
    priority: int
    title: str
    detail: str
    url: str | None = None
    draft: str | None = None


def _host(url: str) -> str:
    return (urlsplit(url).hostname or url).removeprefix("www.")


def _key(prefix: str, value: str) -> str:
    # dedupe_key is stored unencrypted, so anything that could identify the
    # person (a personal domain, say) goes in hashed.
    return f"{prefix}:{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def build_plan(
    *,
    jurisdiction: str,
    holder_name: str,
    contact_email: str,
    verified_emails: list[tuple[str, str]],  # (identifier_id, email)
    findings: list[Finding],
    breaches: list[BreachHit],
    brokers: BrokerRegistry,
) -> list[PlannedItem]:
    # Only results known to be about the account holder get removal steps. A
    # name-only match might be a namesake, and an opt-out letter for a
    # stranger's listing is wasted at best; those wait for the user's verdict.
    about_them = [f for f in findings if f.match_status in ("likely", "confirmed")]
    unclear = [f for f in findings if f.match_status == "unclear"]

    items: list[PlannedItem] = []
    items += _baseline(jurisdiction, verified_emails)
    items += _breach_items(breaches)
    items += _finding_items(jurisdiction, holder_name, contact_email, about_them, brokers)
    if unclear:
        n = len(unclear)
        items.append(
            PlannedItem(
                dedupe_key="review:matches",
                source_type="finding",
                source_id=None,
                action_type="review_matches",
                priority=MEDIUM,
                title=f"Check {n} result{'s' if n != 1 else ''} that may be about someone with your name",
                detail=(
                    "Only your name links these pages to you. Mark each one 'This is me' or 'Not me' on the "
                    "scan page. The ones you confirm get removal steps here; the others are deleted and left "
                    "out of future scans. Adding a city, your birth year or a workplace under Your details "
                    "lets scans sort most of these out on their own."
                ),
            )
        )
    return sorted(items, key=lambda i: (i.priority, i.title))


def _baseline(jurisdiction: str, verified_emails: list[tuple[str, str]]) -> list[PlannedItem]:
    items = [
        PlannedItem(
            dedupe_key=f"baseline:mfa:{identifier_id}",
            source_type="baseline",
            source_id=identifier_id,
            action_type="enable_mfa",
            priority=HIGH,
            title=f"Turn on two-factor authentication for {email}",
            detail=(
                "Your email account is the reset path for nearly every other account, so it is the one "
                "an attacker wants most. Prefer a passkey or an authenticator app over SMS codes, and "
                "store the recovery codes somewhere offline."
            ),
        )
        for identifier_id, email in verified_emails
    ]
    items.append(
        PlannedItem(
            dedupe_key="baseline:password-manager",
            source_type="baseline",
            source_id=None,
            action_type="password_hygiene",
            priority=MEDIUM,
            title="Use a password manager and a unique password per site",
            detail=(
                "Breaches become account takeovers through password reuse. A manager makes unique "
                "passwords practical; start with email, banking and any account listed in a breach above."
            ),
        )
    )
    items.append(
        PlannedItem(
            dedupe_key="baseline:pwned-passwords",
            source_type="baseline",
            source_id=None,
            action_type="password_hygiene",
            priority=MEDIUM,
            title="Check the passwords you still use against Pwned Passwords",
            detail=(
                "POST /breach-check/password-range takes only the first 5 hex characters of a "
                "password's SHA-1 and returns matching suffixes; compare locally. Neither the password "
                "nor its full hash is ever sent to this service. Many password managers run the same "
                "check for you."
            ),
        )
    )
    if jurisdiction == "US-CA":
        items.append(
            PlannedItem(
                dedupe_key="baseline:ca-drop",
                source_type="baseline",
                source_id=None,
                action_type="opt_out",
                priority=HIGH,
                title="File one deletion request with every registered California data broker (DROP)",
                detail=(
                    "Under the California Delete Act, the California Privacy Protection Agency runs "
                    "DROP, a single request that registered data brokers must process. It covers "
                    "brokers this scan cannot see. Start from the agency's site."
                ),
                url="https://cppa.ca.gov/",
            )
        )
    if jurisdiction == "FI":
        items.append(
            PlannedItem(
                dedupe_key="baseline:fi-dvv",
                source_type="baseline",
                source_id=None,
                action_type="opt_out",
                priority=MEDIUM,
                title="Restrict disclosure of your details from the Finnish Population Information System",
                detail=(
                    "The Digital and Population Data Services Agency (DVV) discloses address data for "
                    "purposes such as direct marketing unless you restrict it. Setting restrictions "
                    "there cuts off one of the sources directory services draw from."
                ),
                url="https://dvv.fi/",
            )
        )
    return items


def _breach_items(breaches: list[BreachHit]) -> list[PlannedItem]:
    by_breach: dict[str, list[BreachHit]] = defaultdict(list)
    for b in breaches:
        by_breach[b.breach_name].append(b)
    items = []
    for name, hits in by_breach.items():
        b = hits[0]
        classes = sorted({c for h in hits for c in h.data_classes})
        exposed = ", ".join(classes) or "unspecified data"
        when = f" in {b.breach_date[:4]}" if b.breach_date else ""
        site = b.domain or b.title
        if "Passwords" in classes:
            priority, action = CRITICAL, "change_password"
            title = f"Change your {b.title} password and anywhere you reused it"
            detail = (
                f"{b.title} was breached{when}, exposing: {exposed}. Change the password there if the "
                "account still exists, and on every other site where you used the same or a similar "
                "password. The reuse is what attackers exploit."
            )
        elif _SENSITIVE_CLASSES.intersection(classes):
            priority, action = HIGH, "review_breach"
            title = f"Review what the {b.title} breach exposed"
            detail = (
                f"{b.title} was breached{when}, exposing: {exposed}. Change any security answers that "
                "were exposed, and watch for fraud against any exposed payment or ID data."
            )
        else:
            priority, action = LOW, "review_breach"
            title = f"Expect phishing that uses data from the {b.title} breach"
            detail = (
                f"{b.title} was breached{when}, exposing: {exposed}. No passwords were included, but "
                "messages quoting these details are more convincing; be sceptical of them."
            )
        if not b.is_verified:
            detail += " HIBP lists this breach as unverified."
        items.append(
            PlannedItem(
                dedupe_key=f"breach:{name}",
                source_type="breach",
                source_id=b.id,
                action_type=action,
                priority=priority,
                title=title,
                detail=detail,
                url=f"https://{site}" if b.domain else None,
            )
        )
    return items


def _low_confidence_note(findings: list[Finding]) -> str:
    # Once the account holder has said "this is me", the doubt is settled.
    if all(f.confidence == "low" and f.match_status != "confirmed" for f in findings):
        return " Low confidence: this may be someone with the same name. Check the page before acting."
    return ""


def _finding_items(
    jurisdiction: str,
    holder_name: str,
    contact_email: str,
    findings: list[Finding],
    brokers: BrokerRegistry,
) -> list[PlannedItem]:
    items: list[PlannedItem] = []
    make_letter = letter_for(jurisdiction)

    by_broker: dict[str, list[Finding]] = defaultdict(list)
    removal_hosts: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        if f.broker_id and brokers.get(f.broker_id):
            by_broker[f.broker_id].append(f)
        elif f.category in {"data_broker", "people_search", "paste_or_leak"}:
            removal_hosts[_host(f.url)].append(f)

    for broker_id, group in by_broker.items():
        broker = brokers.get(broker_id)
        urls = sorted({f.url for f in group})
        steps = {
            "web_form": "Submit the opt-out form",
            "email": f"Email the request to {broker.privacy_email}" if broker.privacy_email else "Email the request",
            "letter": "Send the request letter to their privacy contact",
        }.get(broker.method, "Follow their opt-out procedure")
        detail = f"{steps} for each listing ({len(urls)} found). "
        if broker.requires_id_verification:
            detail += "They may ask you to verify your identity; that step is yours to do. "
        if broker.notes:
            detail += broker.notes + " "
        detail += (
            f"Opt-out route last verified: {broker.last_verified}."
            if broker.last_verified
            else "This opt-out route has not been re-verified recently; confirm it on their site."
        )
        detail += _low_confidence_note(group)
        items.append(
            PlannedItem(
                dedupe_key=f"broker:{broker_id}",
                source_type="finding",
                source_id=group[0].id,
                action_type="opt_out",
                priority=LOW if _low_confidence_note(group) else MEDIUM,
                title=f"Opt out of {broker.name}",
                detail=detail.strip(),
                url=broker.opt_out_url,
                draft=make_letter(broker.name, holder_name, contact_email, urls),
            )
        )

    for host, group in removal_hosts.items():
        urls = sorted({f.url for f in group})
        is_leak = any(f.category == "paste_or_leak" for f in group)
        items.append(
            PlannedItem(
                dedupe_key=_key("host", host),
                source_type="finding",
                source_id=group[0].id,
                action_type="takedown" if is_leak else "opt_out",
                priority=HIGH if is_leak else MEDIUM,
                title=f"{'Request takedown from' if is_leak else 'Request removal from'} {host}",
                detail=(
                    ("Leaked data often includes credentials; check the breach items too. " if is_leak else "")
                    + f"{host} is not in the broker registry, so look for its privacy or removal page, "
                    "or send the letter below to its contact address."
                    + _low_confidence_note(group)
                ),
                draft=make_letter(host, holder_name, contact_email, urls),
            )
        )

    for f in findings:
        if f.broker_id or f.category in {"data_broker", "people_search", "paste_or_leak"}:
            continue
        host = _host(f.url)
        if f.category == "possible_impersonation":
            items.append(
                PlannedItem(
                    dedupe_key=_key("finding", f.url),
                    source_type="finding",
                    source_id=f.id,
                    action_type="report_impersonation",
                    priority=HIGH,
                    title=f"Check a possible impersonation profile on {host}",
                    detail=(
                        f"{f.rationale} If the profile is not yours, report it through the platform's "
                        "own flow (usually Report, then 'pretending to be me'). Platforms typically ask the "
                        "impersonated person for ID; that step is yours to do."
                    ),
                    url=f.url,
                )
            )
        elif f.category == "social_profile":
            items.append(
                PlannedItem(
                    dedupe_key=_key("finding", f.url),
                    source_type="finding",
                    source_id=f.id,
                    action_type="review_profile",
                    priority=LOW,
                    title=f"Confirm this {host} profile is yours and review its visibility",
                    detail=(
                        "If it is yours, check what it shows to people who are not logged in. If it is "
                        "an old account you no longer use, delete it from the account settings. If it "
                        "is not yours, treat it as impersonation." + _low_confidence_note([f])
                    ),
                    url=f.url,
                )
            )
        else:
            items.append(
                PlannedItem(
                    dedupe_key=_key("finding", f.url),
                    source_type="finding",
                    source_id=f.id,
                    action_type="review",
                    priority=LOW,
                    title=f"Review a mention on {host}",
                    detail=f.rationale + _low_confidence_note([f]),
                    url=f.url,
                )
            )
    return items
