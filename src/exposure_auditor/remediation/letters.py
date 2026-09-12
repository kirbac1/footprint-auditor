"""Removal-request letters.

Templates, not model output: a legal request should say exactly what we
reviewed it to say, every time. The user sends them; this service never
does, because most recipients will want to verify the sender themselves.
"""

_NOTE = "[Review before sending. This is a template, not legal advice. Delete anything you would rather not share.]"


def _url_list(urls: list[str]) -> str:
    return "\n".join(f"   - {u}" for u in urls) if urls else "   - (any records you hold about me)"


def gdpr_erasure(recipient: str, holder_name: str, contact_email: str, urls: list[str]) -> str:
    return f"""{_NOTE}

Subject: Erasure request and objection under Articles 17 and 21 GDPR

To the data protection officer of {recipient},

I am exercising my rights under the General Data Protection Regulation (EU) 2016/679.

1. Erasure (Article 17). Please erase all personal data you hold about me, including the listings at:
{_url_list(urls)}

2. Objection (Article 21). I object to any further processing of my personal data, including for direct marketing and profiling. Where you rely on legitimate interests, I do not accept that they override my interests, rights and freedoms.

3. Recipients (Article 19). Please inform every recipient to whom you disclosed my data of this erasure, and tell me who they are.

To locate my records you may use: {holder_name}, {contact_email}. Under Article 12(6) you may ask for more information only where you have reasonable doubts about my identity, and only what is necessary to resolve them.

Please respond without undue delay and in any event within one month of receipt (Article 12(3)).

Kind regards,
{holder_name}
"""


_NOTE_FI = (
    "[Tarkista ennen lähettämistä. Tämä on malliteksti, ei oikeudellinen neuvo. "
    "Poista tiedot, joita et halua jakaa.]"
)


def gdpr_erasure_fi(recipient: str, holder_name: str, contact_email: str, urls: list[str]) -> str:
    """The GDPR letter in Finnish, for a Finnish recipient."""
    listing = "\n".join(f"   - {u}" for u in urls) if urls else "   - (kaikki minua koskevat tietonne)"
    return f"""{_NOTE_FI}

Aihe: Tietojen poistamista ja käsittelyn vastustamista koskeva pyyntö (tietosuoja-asetus, 17 ja 21 artikla)

{recipient} / tietosuojavastaava

Käytän EU:n yleisen tietosuoja-asetuksen (EU) 2016/679 mukaisia oikeuksiani.

1. Tietojen poistaminen (17 artikla). Pyydän poistamaan kaikki minua koskevat henkilötiedot, mukaan lukien seuraavat julkaisut:
{listing}

2. Käsittelyn vastustaminen (21 artikla). Vastustan henkilötietojeni käsittelyä, myös suoramarkkinointia ja profilointia varten. Jos käsittely perustuu oikeutettuun etuunne, katson, ettei se syrjäytä etujani, oikeuksiani ja vapauksiani.

3. Vastaanottajat (19 artikla). Pyydän ilmoittamaan poistosta kaikille, joille olette luovuttaneet tietojani, ja kertomaan minulle, keitä he ovat.

Tietojeni löytämiseksi voitte käyttää seuraavia tietoja: {holder_name}, {contact_email}. 12 artiklan 6 kohdan mukaan voitte pyytää lisätietoja vain, jos teillä on perusteltua syytä epäillä henkilöllisyyttäni, ja vain sen verran kuin on tarpeen.

Pyydän vastaamaan ilman aiheetonta viivytystä ja viimeistään kuukauden kuluessa pyynnön vastaanottamisesta (12 artiklan 3 kohta).

Ystävällisin terveisin
{holder_name}
"""


def ccpa_delete(recipient: str, holder_name: str, contact_email: str, urls: list[str]) -> str:
    return f"""{_NOTE}

Subject: Request to delete and to opt out of sale and sharing (CCPA)

To {recipient},

I am a California resident exercising my rights under the California Consumer Privacy Act, as amended by the California Privacy Rights Act.

1. Delete (Cal. Civ. Code 1798.105). Please delete all personal information you have collected about me, including the listings at:
{_url_list(urls)}
   and direct your service providers and contractors to do the same.

2. Opt out of sale and sharing (Cal. Civ. Code 1798.120). Do not sell or share my personal information.

To locate my records you may use: {holder_name}, {contact_email}.

Please confirm receipt within 10 business days and respond within 45 calendar days, as the CCPA and its regulations require.

Regards,
{holder_name}
"""


def general_removal(recipient: str, holder_name: str, contact_email: str, urls: list[str]) -> str:
    return f"""{_NOTE}

Subject: Request to remove my personal information

To {recipient},

Please remove the personal information about me published at:
{_url_list(urls)}

and stop collecting, selling or sharing personal information about me. If a privacy law that applies to you gives me a right to deletion, please treat this as a request under it.

To locate my records you may use: {holder_name}, {contact_email}.

Please confirm when the removal is complete.

Regards,
{holder_name}
"""


def letter_for(jurisdiction: str, legal_bases: tuple[str, ...] = ()):
    """Pick the template that gives the reader the strongest footing."""
    if jurisdiction in {"EU", "FI"}:
        # GDPR reaches non-EU controllers that monitor people in the EU
        # (Article 3(2)), which is what a profile of an EU resident is.
        return gdpr_erasure
    if jurisdiction == "US-CA":
        return ccpa_delete
    return general_removal
