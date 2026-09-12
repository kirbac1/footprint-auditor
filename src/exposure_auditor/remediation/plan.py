"""Turn scan findings and breach hits into a prioritized list of things to do.

Pure and deterministic: same inputs, same plan. The persistence layer
(remediation/service.py) upserts these by dedupe_key so the user's progress
on an item survives a rebuild.

Item text comes in English or Finnish. Letters follow the recipient, not
the reader: a Finnish letter only goes to a Finnish recipient, and Spokeo
gets English whatever language the plan is in.
"""

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..models import BreachHit, Finding
from ..tools.brokers import BrokerRegistry
from .letters import gdpr_erasure_fi, letter_for

CRITICAL, HIGH, MEDIUM, LOW = 0, 1, 2, 3
JURISDICTIONS = ("EU", "FI", "US-CA", "US", "OTHER")
LANGUAGES = ("en", "fi")

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

_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "mfa.title": "Turn on two-factor authentication for {email}",
        "mfa.detail": (
            "Your email account is the reset path for nearly every other account, so it is the one an attacker "
            "wants most. Prefer a passkey or an authenticator app over SMS codes, and store the recovery codes "
            "somewhere offline."
        ),
        "pm.title": "Use a password manager and a unique password per site",
        "pm.detail": (
            "Breaches become account takeovers through password reuse. A manager makes unique passwords practical; "
            "start with email, banking and any account listed in a breach above."
        ),
        "pwned.title": "Check the passwords you still use against known breaches",
        "pwned.detail": (
            "Use the check on the Breaches tab: the password is hashed in your browser and only the first 5 "
            "characters of the hash are sent. Many password managers run the same check for you."
        ),
        "drop.title": "File one deletion request with every registered California data broker (DROP)",
        "drop.detail": (
            "Under the California Delete Act, the California Privacy Protection Agency runs DROP, a single request "
            "that registered data brokers must process. It covers brokers this scan cannot see. Start from the "
            "agency's site."
        ),
        "dvv.title": "Ban disclosure of your details from the Finnish Population Information System",
        "dvv.detail": (
            "The Digital and Population Data Services Agency (DVV) discloses address data for purposes such as "
            "direct marketing unless you ban it. You set the bans on the Personal Information page of Suomi.fi, "
            "and they stay in force until you lift them. Phone numbers aren't in the register; those go through "
            "your operator."
        ),
        "dvv.url": "https://dvv.fi/en/non-disclosure-of-personal-data",
        "operator.title": "Ask your phone operator to hide your number and address from directory services",
        "operator.detail": (
            "Directory services such as Fonecta's Finder get numbers and addresses from telecom operators. Fonecta "
            "asks people to make removal requests through their operator, who passes them on to every directory "
            "service. Ask for an unlisted (secret) number and address."
        ),
        "breach.when": " in {year}",
        "breach.unspecified": "unspecified data",
        "breach.pw.title": "Change your {title} password and anywhere you reused it",
        "breach.pw.detail": (
            "{title} was breached{when}, exposing: {exposed}. Change the password there if the account still "
            "exists, and on every other site where you used the same or a similar password. The reuse is what "
            "attackers exploit."
        ),
        "breach.sensitive.title": "Review what the {title} breach exposed",
        "breach.sensitive.detail": (
            "{title} was breached{when}, exposing: {exposed}. Change any security answers that were exposed, and "
            "watch for fraud against any exposed payment or ID data."
        ),
        "breach.low.title": "Expect phishing that uses data from the {title} breach",
        "breach.low.detail": (
            "{title} was breached{when}, exposing: {exposed}. No passwords were included, but messages quoting "
            "these details are more convincing; be sceptical of them."
        ),
        "breach.unverified": " HIBP lists this breach as unverified.",
        "step.web_form": "Submit the opt-out form",
        "step.email": "Email the request to {email}",
        "step.email_generic": "Email the request",
        "step.letter": "Send the request letter to their privacy contact",
        "step.operator": "Ask your phone operator to hide your number and address",
        "step.other": "Follow their opt-out procedure",
        "broker.title": "Opt out of {name}",
        "broker.detail": "{steps} for each listing ({n} found). ",
        "broker.id_check": "They may ask you to verify your identity; that step is yours to do. ",
        "broker.verified": "Opt-out route last verified: {date}.",
        "broker.unverified": "This opt-out route has not been re-verified recently; confirm it on their site.",
        "low_confidence": " Low confidence: this may be someone with the same name. Check the page before acting.",
        "host.takedown.title": "Request takedown from {host}",
        "host.removal.title": "Request removal from {host}",
        "host.leak": "Leaked data often includes credentials; check the breach items too. ",
        "host.detail": (
            "{host} is not in the broker registry, so look for its privacy or removal page, or send the letter "
            "below to its contact address."
        ),
        "imp.title": "Check a possible impersonation profile on {host}",
        "imp.detail": (
            "{rationale} If the profile is not yours, report it through the platform's own flow (usually Report, "
            "then 'pretending to be me'). Platforms typically ask the impersonated person for ID; that step is "
            "yours to do."
        ),
        "social.title": "Confirm this {host} profile is yours and review its visibility",
        "social.detail": (
            "If it is yours, check what it shows to people who are not logged in. If it is an old account you no "
            "longer use, delete it from the account settings. If it is not yours, treat it as impersonation."
        ),
        "mention.title": "Review a mention on {host}",
        "review.title.one": "Check 1 result that may be about someone with your name",
        "review.title.many": "Check {n} results that may be about someone with your name",
        "review.detail": (
            "Only your name links these pages to you. Mark each one 'This is me' or 'Not me' on the scan page. The "
            "ones you confirm get removal steps here; the others are deleted and left out of future scans. Adding a "
            "city, your birth year or a workplace under Your details lets scans sort most of these out on their own."
        ),
    },
    "fi": {
        "mfa.title": "Ota kaksivaiheinen tunnistautuminen käyttöön tilillä {email}",
        "mfa.detail": (
            "Sähköpostitilin kautta voi palauttaa lähes kaikkien muiden tiliesi salasanat, joten se on hyökkääjälle "
            "arvokkain. Käytä mieluummin pääsyavainta tai todennussovellusta kuin tekstiviestikoodeja, ja säilytä "
            "palautuskoodit muualla kuin verkossa."
        ),
        "pm.title": "Käytä salasanojen hallintaa ja eri salasanaa jokaisessa palvelussa",
        "pm.detail": (
            "Tietomurroista tulee tilikaappauksia, kun samaa salasanaa käytetään monessa paikassa. Salasanojen "
            "hallinta tekee eri salasanoista helppoja. Aloita sähköpostista, pankista ja yllä mainituista "
            "tietomurtojen tileistä."
        ),
        "pwned.title": "Tarkista, löytyvätkö käyttämäsi salasanat tunnetuista tietomurroista",
        "pwned.detail": (
            "Käytä Tietomurrot-välilehden tarkistusta: salasana tiivistetään selaimessasi, ja vain tiivisteen viisi "
            "ensimmäistä merkkiä lähetetään. Monet salasanojen hallintaohjelmat tekevät saman tarkistuksen puolestasi."
        ),
        "drop.title": "Tee yksi poistopyyntö kaikille Kalifornian rekisteröidyille tietovälittäjille (DROP)",
        "drop.detail": (
            "Kalifornian Delete Act -lain nojalla Kalifornian tietosuojavirasto ylläpitää DROP-palvelua: yhden "
            "pyynnön, joka rekisteröityjen tietovälittäjien on käsiteltävä. Se kattaa myös välittäjät, joita tämä "
            "skannaus ei näe. Aloita viraston sivuilta."
        ),
        "dvv.title": "Kiellä tietojesi luovuttaminen väestötietojärjestelmästä",
        "dvv.detail": (
            "Digi- ja väestötietovirasto (DVV) luovuttaa osoitetietoja esimerkiksi suoramarkkinointiin, ellet kiellä "
            "sitä. Kiellot tehdään Suomi.fi-palvelun Omat tiedot -sivulla, ja ne ovat voimassa, kunnes perut ne. "
            "Puhelinnumerot eivät ole väestötietojärjestelmässä; ne hoidetaan operaattorin kautta."
        ),
        "dvv.url": "https://dvv.fi/tietojen-luovuttamisen-kieltaminen",
        "operator.title": "Pyydä puhelinoperaattoriasi piilottamaan numerosi ja osoitteesi numeropalveluista",
        "operator.detail": (
            "Numeropalvelut, kuten Fonectan Finder, saavat numerot ja osoitteet teleoperaattoreilta. Fonecta ohjaa "
            "tekemään poistopyynnöt oman operaattorin kautta, joka välittää ne kaikille numeropalveluille. Pyydä "
            "salaista numeroa ja osoitetta."
        ),
        "breach.when": " vuonna {year}",
        "breach.unspecified": "tarkemmin määrittelemättömiä tietoja",
        "breach.pw.title": "Vaihda palvelun {title} salasana ja kaikki samat salasanat muualla",
        "breach.pw.detail": (
            "{title} joutui tietomurron kohteeksi{when}, ja vuodossa paljastui: {exposed}. Vaihda salasana "
            "palvelussa, jos tili on yhä olemassa, ja kaikissa muissa palveluissa, joissa käytit samaa tai "
            "samankaltaista salasanaa. Hyökkääjät käyttävät juuri uudelleenkäyttöä hyväkseen."
        ),
        "breach.sensitive.title": "Tarkista, mitä palvelun {title} tietomurrossa paljastui",
        "breach.sensitive.detail": (
            "{title} joutui tietomurron kohteeksi{when}, ja vuodossa paljastui: {exposed}. Vaihda paljastuneet "
            "turvakysymysten vastaukset ja seuraa, käytetäänkö paljastuneita maksu- tai henkilöllisyystietoja väärin."
        ),
        "breach.low.title": "Varaudu tietojenkalasteluun, jossa käytetään palvelun {title} vuotaneita tietoja",
        "breach.low.detail": (
            "{title} joutui tietomurron kohteeksi{when}, ja vuodossa paljastui: {exposed}. Salasanoja ei vuotanut, "
            "mutta näitä tietoja lainaavat viestit vaikuttavat uskottavammilta. Suhtaudu niihin epäillen."
        ),
        "breach.unverified": " HIBP:n mukaan tätä tietomurtoa ei ole vahvistettu.",
        "step.web_form": "Täytä poistolomake",
        "step.email": "Lähetä pyyntö osoitteeseen {email}",
        "step.email_generic": "Lähetä pyyntö sähköpostilla",
        "step.letter": "Lähetä pyyntökirje heidän tietosuojayhteyshenkilölleen",
        "step.operator": "Pyydä operaattoriasi piilottamaan numerosi ja osoitteesi",
        "step.other": "Noudata heidän poisto-ohjettaan",
        "broker.title": "Poista tietosi palvelusta {name}",
        "broker.detail": "{steps} jokaisesta ilmoituksesta ({n} löytyi). ",
        "broker.id_check": "He saattavat pyytää todistamaan henkilöllisyytesi; se vaihe jää sinulle. ",
        "broker.verified": "Poistoreitti tarkistettu viimeksi: {date}.",
        "broker.unverified": "Tätä poistoreittiä ei ole tarkistettu hiljattain; varmista se palvelun sivuilta.",
        "low_confidence": " Epävarma: tämä voi koskea samannimistä henkilöä. Tarkista sivu ennen kuin toimit.",
        "host.takedown.title": "Pyydä poistoa palvelusta {host}",
        "host.removal.title": "Pyydä tietojesi poistoa palvelusta {host}",
        "host.leak": "Vuodetut tiedot sisältävät usein tunnuksia; katso myös tietomurtokohdat. ",
        "host.detail": (
            "{host} ei ole tietovälittäjäluettelossa, joten etsi sen tietosuoja- tai poistosivu tai lähetä alla "
            "oleva kirje sen yhteysosoitteeseen."
        ),
        "imp.title": "Tarkista mahdollinen tekaistu profiili palvelussa {host}",
        "imp.detail": (
            "{rationale} Jos profiili ei ole sinun, ilmoita siitä palvelun omalla toiminnolla (yleensä Ilmoita, "
            "sitten ”esiintyy minuna”). Palvelut pyytävät yleensä esiintymisen kohteelta henkilöllisyystodistusta; "
            "se vaihe jää sinulle."
        ),
        "social.title": "Varmista, että profiili palvelussa {host} on sinun, ja tarkista sen näkyvyys",
        "social.detail": (
            "Jos profiili on sinun, tarkista, mitä se näyttää kirjautumattomille. Jos se on vanha tili, jota et enää "
            "käytä, poista se tilin asetuksista. Jos se ei ole sinun, käsittele sitä tekaistuna profiilina."
        ),
        "mention.title": "Tarkista maininta palvelussa {host}",
        "review.title.one": "Tarkista 1 tulos, joka voi koskea samannimistä henkilöä",
        "review.title.many": "Tarkista {n} tulosta, jotka voivat koskea samannimisiä henkilöitä",
        "review.detail": (
            "Vain nimesi yhdistää nämä sivut sinuun. Merkitse jokainen skannaussivulla ”Tämä olen minä” tai ”En ole "
            "minä”. Vahvistamillesi tulee tähän poisto-ohjeet; muut poistetaan, eikä niitä näytetä tulevissa "
            "skannauksissa. Kun lisäät Omat tiedot -kohtaan kaupungin, syntymävuoden tai työpaikan, skannaus osaa "
            "lajitella useimmat näistä itse."
        ),
    },
}


def _t(language: str, key: str, **values: object) -> str:
    return _TEXT[language][key].format(**values)


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
    language: str = "en",
) -> list[PlannedItem]:
    language = language if language in LANGUAGES else "en"
    # Only results known to be about the account holder get removal steps. A
    # name-only match might be a namesake, and an opt-out letter for a
    # stranger's listing is wasted at best; those wait for the user's verdict.
    about_them = [f for f in findings if f.match_status in ("likely", "confirmed")]
    unclear = [f for f in findings if f.match_status == "unclear"]

    items: list[PlannedItem] = []
    items += _baseline(jurisdiction, language, verified_emails)
    items += _breach_items(language, breaches)
    items += _finding_items(jurisdiction, language, holder_name, contact_email, about_them, brokers)
    if unclear:
        n = len(unclear)
        items.append(
            PlannedItem(
                dedupe_key="review:matches",
                source_type="finding",
                source_id=None,
                action_type="review_matches",
                priority=MEDIUM,
                title=_t(language, "review.title.one" if n == 1 else "review.title.many", n=n),
                detail=_t(language, "review.detail"),
            )
        )
    return sorted(items, key=lambda i: (i.priority, i.title))


def _baseline(jurisdiction: str, language: str, verified_emails: list[tuple[str, str]]) -> list[PlannedItem]:
    items = [
        PlannedItem(
            dedupe_key=f"baseline:mfa:{identifier_id}",
            source_type="baseline",
            source_id=identifier_id,
            action_type="enable_mfa",
            priority=HIGH,
            title=_t(language, "mfa.title", email=email),
            detail=_t(language, "mfa.detail"),
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
            title=_t(language, "pm.title"),
            detail=_t(language, "pm.detail"),
        )
    )
    items.append(
        PlannedItem(
            dedupe_key="baseline:pwned-passwords",
            source_type="baseline",
            source_id=None,
            action_type="password_hygiene",
            priority=MEDIUM,
            title=_t(language, "pwned.title"),
            detail=_t(language, "pwned.detail"),
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
                title=_t(language, "drop.title"),
                detail=_t(language, "drop.detail"),
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
                title=_t(language, "dvv.title"),
                detail=_t(language, "dvv.detail"),
                url=_t(language, "dvv.url"),
            )
        )
        items.append(
            PlannedItem(
                dedupe_key="baseline:fi-operator",
                source_type="baseline",
                source_id=None,
                action_type="opt_out",
                priority=MEDIUM,
                title=_t(language, "operator.title"),
                detail=_t(language, "operator.detail"),
            )
        )
    return items


def _breach_items(language: str, breaches: list[BreachHit]) -> list[PlannedItem]:
    by_breach: dict[str, list[BreachHit]] = defaultdict(list)
    for b in breaches:
        by_breach[b.breach_name].append(b)
    items = []
    for name, hits in by_breach.items():
        b = hits[0]
        classes = sorted({c for h in hits for c in h.data_classes})
        values = {
            "title": b.title,
            "exposed": ", ".join(classes) or _t(language, "breach.unspecified"),
            "when": _t(language, "breach.when", year=b.breach_date[:4]) if b.breach_date else "",
        }
        if "Passwords" in classes:
            priority, action, kind = CRITICAL, "change_password", "pw"
        elif _SENSITIVE_CLASSES.intersection(classes):
            priority, action, kind = HIGH, "review_breach", "sensitive"
        else:
            priority, action, kind = LOW, "review_breach", "low"
        detail = _t(language, f"breach.{kind}.detail", **values)
        if not b.is_verified:
            detail += _t(language, "breach.unverified")
        items.append(
            PlannedItem(
                dedupe_key=f"breach:{name}",
                source_type="breach",
                source_id=b.id,
                action_type=action,
                priority=priority,
                title=_t(language, f"breach.{kind}.title", **values),
                detail=detail,
                url=f"https://{b.domain}" if b.domain else None,
            )
        )
    return items


def _low_confidence_note(language: str, findings: list[Finding]) -> str:
    # Once the account holder has said "this is me", the doubt is settled.
    if all(f.confidence == "low" and f.match_status != "confirmed" for f in findings):
        return _t(language, "low_confidence")
    return ""


def _letter(jurisdiction: str, language: str, finnish_recipient: bool):
    if language == "fi" and finnish_recipient:
        return gdpr_erasure_fi
    return letter_for(jurisdiction)


def _finding_items(
    jurisdiction: str,
    language: str,
    holder_name: str,
    contact_email: str,
    findings: list[Finding],
    brokers: BrokerRegistry,
) -> list[PlannedItem]:
    items: list[PlannedItem] = []

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
        if broker.method == "email":
            steps = (_t(language, "step.email", email=broker.privacy_email) if broker.privacy_email
                     else _t(language, "step.email_generic"))
        elif broker.method in ("web_form", "letter", "operator"):
            steps = _t(language, f"step.{broker.method}")
        else:
            steps = _t(language, "step.other")
        detail = _t(language, "broker.detail", steps=steps, n=len(urls))
        if broker.requires_id_verification:
            detail += _t(language, "broker.id_check")
        notes = broker.notes_fi if language == "fi" and broker.notes_fi else broker.notes
        if notes:
            detail += notes + " "
        detail += (
            _t(language, "broker.verified", date=broker.last_verified)
            if broker.last_verified
            else _t(language, "broker.unverified")
        )
        low = _low_confidence_note(language, group)
        make_letter = _letter(jurisdiction, language, finnish_recipient="FI" in broker.jurisdictions)
        items.append(
            PlannedItem(
                dedupe_key=f"broker:{broker_id}",
                source_type="finding",
                source_id=group[0].id,
                action_type="opt_out",
                priority=LOW if low else MEDIUM,
                title=_t(language, "broker.title", name=broker.name),
                detail=(detail + low).strip(),
                url=broker.opt_out_url,
                draft=make_letter(broker.name, holder_name, contact_email, urls),
            )
        )

    for host, group in removal_hosts.items():
        urls = sorted({f.url for f in group})
        is_leak = any(f.category == "paste_or_leak" for f in group)
        make_letter = _letter(jurisdiction, language, finnish_recipient=host.endswith(".fi"))
        items.append(
            PlannedItem(
                dedupe_key=_key("host", host),
                source_type="finding",
                source_id=group[0].id,
                action_type="takedown" if is_leak else "opt_out",
                priority=HIGH if is_leak else MEDIUM,
                title=_t(language, "host.takedown.title" if is_leak else "host.removal.title", host=host),
                detail=(
                    (_t(language, "host.leak") if is_leak else "")
                    + _t(language, "host.detail", host=host)
                    + _low_confidence_note(language, group)
                ),
                draft=make_letter(host, holder_name, contact_email, urls),
            )
        )

    for f in findings:
        if f.broker_id or f.category in {"data_broker", "people_search", "paste_or_leak"}:
            continue
        host = _host(f.url)
        if f.category == "possible_impersonation":
            action, priority, key = "report_impersonation", HIGH, "imp"
            detail = _t(language, "imp.detail", rationale=f.rationale)
        elif f.category == "social_profile":
            action, priority, key = "review_profile", LOW, "social"
            detail = _t(language, "social.detail") + _low_confidence_note(language, [f])
        else:
            action, priority, key = "review", LOW, "mention"
            detail = f.rationale + _low_confidence_note(language, [f])
        items.append(
            PlannedItem(
                dedupe_key=_key("finding", f.url),
                source_type="finding",
                source_id=f.id,
                action_type=action,
                priority=priority,
                title=_t(language, f"{key}.title", host=host),
                detail=detail,
                url=f.url,
            )
        )
    return items
