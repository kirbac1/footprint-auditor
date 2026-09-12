import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type Lang = "en" | "fi";

const en = {
  "app.signOut": "Sign out",
  "app.donate": "Donate via PayPal",
  "app.demoTitle": "Demo mode.",
  "app.demoBody":
    "Scans run the real pipeline against a scripted model and synthetic search results. Scan findings on this server are not real.",
  "app.otherLanguage": "Suomi",
  "app.languageLabel": "Vaihda kieli suomeksi",

  "auth.title": "See where your personal data is exposed.",
  "auth.lead":
    "Footprint searches the public web for your own details, checks your email against known breaches, and turns what it finds into a plan: opt-out links, removal letters ready to send, and steps to lock down your accounts.",
  "auth.fact1": "It only searches for details you have proven, or confirmed, are yours.",
  "auth.fact2": "It never deletes anything or sends requests on your behalf. You stay in control of every step.",
  "auth.fact3": "Your personal details are stored encrypted, and you can erase your account at any time.",
  "auth.signIn": "Sign in",
  "auth.createAccount": "Create account",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.passwordHint": "At least 12 characters.",
  "auth.wait": "Please wait…",
  "auth.accountExists": "If this email already has an account, sign in with that account's password.",

  "tab.details": "Your details",
  "tab.scan": "Footprint scan",
  "tab.breaches": "Breaches",
  "tab.plan": "Action plan",
  "tab.account": "Account",
  "dash.verifyBefore": "Verify an email address or phone number under",
  "dash.verifyAfter": "first. Scans and breach lookups only cover details you have proven are yours.",

  "kind.email": "Email",
  "kind.phone": "Phone",
  "kind.name": "Name",
  "kind.username": "Username",
  "kind.image": "Photo",
  "kind.city": "City",
  "kind.birth_year": "Birth year",
  "kind.workplace": "Workplace",
  "status.pending": "Awaiting code",
  "status.verified": "Verified",
  "status.attested": "Confirmed by you",
  "status.notVerified": "Not verified",
  "status.verifiedVia": "Verified via {platform}",

  "details.title": "Your details",
  "details.intro":
    "Checks only ever cover what is listed here. Emails and phone numbers are verified with a one-time code. Usernames are proven by putting a code in your GitHub or Bluesky bio. Names and photos can't be verified automatically, so you confirm they're yours. Nothing is used until you have verified an email or phone.",
  "details.empty": "Nothing added yet. Start with your email address.",
  "details.remove": "Remove",
  "details.removeConfirm": "Remove this detail ({kind}) and everything found for it?",
  "details.codePlaceholder": "6-digit code",
  "details.codeLabel": "Verification code for {value}",
  "details.verify": "Verify",
  "details.resend": "Send a new code",
  "details.codeSent": "A new code is on its way.",
  "details.consoleHint": "Local server: the code is printed in the API log.",
  "details.addTitle": "Add a detail",
  "details.kindLabel": "Kind",
  "details.valueLabel": "Value",
  "details.optEmail": "Email",
  "details.optPhone": "Phone",
  "details.optName": "Full name",
  "details.optUsername": "Username",
  "details.add": "Add",
  "details.addAndSend": "Add and send code",
  "details.attestUsername": "This username is mine. Next, I'll prove it with a code in my profile bio.",
  "details.attestName": "This name is mine. I understand Footprint can't verify it and relies on my word.",
  "ph.email": "you@example.com",
  "ph.phone": "+358 40 123 4567",
  "ph.name": "First Last",
  "ph.username": "your_handle",
  "ph.city": "A city you live or have lived in",
  "ph.birth_year": "1990",
  "ph.workplace": "An employer or school",

  "context.title": "Tell yourself apart from people with the same name",
  "context.intro":
    "Many people share a name. A city, your birth year or a workplace lets the scan keep results about you and leave out the ones about someone else. These details are only used for that comparison. They are never searched for on their own.",
  "context.detailLabel": "Detail",
  "context.valueLabel": "Detail value",
  "context.optCity": "City",
  "context.optBirthYear": "Birth year",
  "context.optWorkplace": "Workplace or school",

  "photo.title": "Add a photo of you",
  "photo.intro": "Used by the impersonation check to find profiles reusing your picture.",
  "photo.noReverse": " Reverse-image search is not configured on this server yet.",
  "photo.label": "Photo",
  "photo.upload": "Upload",
  "photo.attest": "This is a photo of me.",

  "proof.instructions":
    "Add this code anywhere in your {platform} profile bio, save it, then check. You can delete it again once you're verified.",
  "proof.copy": "Copy",
  "proof.open": "Open {platform}",
  "proof.check": "Check my profile",
  "proof.checking": "Checking…",
  "proof.newCode": "Get a new code",
  "proof.required": "Not used in scans until you prove it's yours:",
  "proof.optional": "Prove it's yours:",
  "proof.getCode": "Get a code",
  "proof.platformLabel": "Platform to prove {value} on",

  "cat.data_broker": "Data broker",
  "cat.people_search": "People-search site",
  "cat.social_profile": "Social profile",
  "cat.possible_impersonation": "Possible impersonation",
  "cat.paste_or_leak": "Paste or leak site",
  "cat.news_or_public_record": "News or public record",
  "cat.other": "Other",
  "scanKind.exposure": "Footprint scan",
  "scanKind.impersonation": "Impersonation check",
  "scanStatus.queued": "queued",
  "scanStatus.running": "running",
  "scanStatus.completed": "completed",
  "scanStatus.failed": "failed",
  "scanStatus.refused": "refused",

  "scan.title": "Check your digital footprint",
  "scan.intro":
    "The scan searches the public web, data brokers and people-search sites for the details you've added. It can take a few minutes. You can leave this page; results are saved to your account.",
  "scan.contextTip":
    "Tip: add a city, birth year or workplace under Your details. The scan uses them to leave out people who only share your name.",
  "scan.start": "Scan my footprint",
  "scan.impersonation": "Check for impersonation",
  "scan.reason.verify": "Verify an email or phone first.",
  "scan.reason.notConfigured": "Scanning is not configured on this server (model or web search missing).",
  "scan.reason.profile": "Add your name, a username or a photo first.",
  "scan.limits": "Up to {n} scans per day, one at a time.",
  "scan.earlier": "Earlier scans",
  "scan.view": "View",
  "scan.scanning": "Scanning…",
  "scan.progress": "Searching. This page updates by itself.",
  "scan.leftOutOne":
    "Left out 1 result about someone with your name. It contradicted your details and was not saved.",
  "scan.leftOutMany":
    "Left out {n} results about other people with your name. They contradicted your details and were not saved.",
  "scan.nothing": "Nothing found for your details in this scan.",
  "scan.aboutYou": "About you",
  "scan.maybeOthers": "Might be someone with your name",
  "scan.reviewHint":
    "Only your name links these to you. The ones you confirm get removal steps. The others are deleted and left out of future scans.",
  "scan.thisIsMe": "This is me",
  "scan.notMe": "Not me",
  "scan.seePlan": "See what to do about these",
  "scan.confirmed": "Confirmed by you",
  "conf.high": "high confidence",
  "conf.medium": "medium confidence",
  "conf.low": "low confidence",
  "usage.model": "Model calls",
  "usage.tools": "Tool calls",
  "usage.tokens": "Tokens",
  "trace.title": "How this scan ran",
  "trace.intro":
    "Every model and tool call, with outcome, timing and token counts. Traces never contain your details or page content.",
  "trace.step": "Step",
  "trace.outcome": "Outcome",
  "trace.start": "Start",
  "trace.took": "Took",
  "trace.tokens": "Tokens in / out",
  "trace.model": "Model",

  "breach.title": "Is your email in a data breach?",
  "breach.intro": "Looks up your verified email addresses in Have I Been Pwned. Only addresses you've verified are sent.",
  "breach.checking": "Checking…",
  "breach.check": "Check my verified emails",
  "breach.notConfigured": "Breach lookups are not configured on this server (needs an HIBP API key).",
  "breach.none": "No known breaches for your verified emails ({n} checked).",
  "breach.passwords": "Passwords exposed",
  "breach.inPlan": "Each breach is now an item in your action plan.",
  "pw.title": "Has a password leaked?",
  "pw.intro":
    "Your password never leaves this browser. It is hashed here, and only the first 5 characters of the hash are sent. The match is checked on your side.",
  "pw.placeholder": "A password you use",
  "pw.label": "Password to check",
  "pw.check": "Check",
  "pw.seen": "Seen {n} times in breaches. Stop using it anywhere and change it where you have.",
  "pw.notFound": "Not found in known breaches. That doesn't make it strong, just not known.",
  "pw.sent": "Sent to the server: {prefix}",

  "jur.FI": "Finland",
  "jur.EU": "EU / EEA",
  "jur.US-CA": "California",
  "jur.US": "Elsewhere in the US",
  "jur.OTHER": "Somewhere else",
  "prio.0": "Do this first",
  "prio.1": "High priority",
  "prio.2": "Worth doing",
  "prio.3": "When you have time",
  "item.open": "To do",
  "item.sent": "Request sent",
  "item.done": "Done",
  "item.dismissed": "Not relevant",
  "plan.title": "Your action plan",
  "plan.liveIn": "I live in",
  "plan.intro":
    "Built from your scans and breach checks. Where you live decides which removal law the letters cite. Nothing here is sent for you. Removal requests are yours to send, and some sites will ask you to prove who you are.",
  "plan.progress": "{done} of {total} done",
  "plan.building": "Building your plan…",
  "plan.openOptOut": "Open the opt-out page",
  "plan.openPage": "Open page",
  "plan.letter": "Removal request letter",
  "plan.copyLetter": "Copy letter",
  "plan.copied": "Copied",
  "plan.statusLabel": "Status of {title}",

  "account.title": "Account",
  "account.signedInAs": "Signed in as",
  "account.since": "Member since",
  "account.eraseTitle": "Erase my account",
  "account.eraseBody":
    "Deletes your account, every detail you added, all scans and findings, breach results and your action plan. This can't be undone. A log of actions, holding ids only and none of your details, is kept for security.",
  "account.confirmWord": "erase",
  "account.typeToConfirm": "Type “{word}” to confirm",
  "account.eraseButton": "Erase everything",
};

export type MessageKey = keyof typeof en;

const fi: Record<MessageKey, string> = {
  "app.signOut": "Kirjaudu ulos",
  "app.donate": "Lahjoita PayPalilla",
  "app.demoTitle": "Demotila.",
  "app.demoBody":
    "Skannaukset ajavat oikean käsittelyketjun käsikirjoitettua mallia ja keksittyjä hakutuloksia vastaan. Tämän palvelimen löydökset eivät ole todellisia.",
  "app.otherLanguage": "English",
  "app.languageLabel": "Switch to English",

  "auth.title": "Katso, missä henkilötietosi näkyvät.",
  "auth.lead":
    "Footprint etsii julkisesta verkosta omia tietojasi, tarkistaa sähköpostisi tunnetuista tietomurroista ja tekee löydöksistä suunnitelman: poistolinkit, valmiit poistopyyntökirjeet ja ohjeet tiliesi suojaamiseen.",
  "auth.fact1": "Se etsii vain tietoja, jotka olet todistanut tai vahvistanut omiksesi.",
  "auth.fact2": "Se ei koskaan poista mitään eikä lähetä pyyntöjä puolestasi. Päätät itse jokaisesta vaiheesta.",
  "auth.fact3": "Henkilötietosi tallennetaan salattuina, ja voit poistaa tilisi milloin tahansa.",
  "auth.signIn": "Kirjaudu",
  "auth.createAccount": "Luo tili",
  "auth.email": "Sähköposti",
  "auth.password": "Salasana",
  "auth.passwordHint": "Vähintään 12 merkkiä.",
  "auth.wait": "Hetki…",
  "auth.accountExists": "Jos tällä sähköpostilla on jo tili, kirjaudu sen salasanalla.",

  "tab.details": "Omat tiedot",
  "tab.scan": "Skannaus",
  "tab.breaches": "Tietomurrot",
  "tab.plan": "Toimintasuunnitelma",
  "tab.account": "Tili",
  "dash.verifyBefore": "Vahvista ensin sähköpostiosoite tai puhelinnumero kohdassa",
  "dash.verifyAfter": ". Skannaukset ja tietomurtohaut koskevat vain tietoja, jotka olet todistanut omiksesi.",

  "kind.email": "Sähköposti",
  "kind.phone": "Puhelin",
  "kind.name": "Nimi",
  "kind.username": "Käyttäjänimi",
  "kind.image": "Kuva",
  "kind.city": "Kaupunki",
  "kind.birth_year": "Syntymävuosi",
  "kind.workplace": "Työpaikka",
  "status.pending": "Odottaa koodia",
  "status.verified": "Vahvistettu",
  "status.attested": "Itse vahvistettu",
  "status.notVerified": "Ei vahvistettu",
  "status.verifiedVia": "Vahvistettu: {platform}",

  "details.title": "Omat tiedot",
  "details.intro":
    "Tarkistukset koskevat vain tähän lisättyjä tietoja. Sähköpostit ja puhelinnumerot vahvistetaan kertakäyttöisellä koodilla. Käyttäjänimet todistetaan lisäämällä koodi GitHub- tai Bluesky-profiilin esittelytekstiin. Nimiä ja kuvia ei voi tarkistaa automaattisesti, joten vahvistat ne itse omiksesi. Mitään ei käytetä ennen kuin olet vahvistanut sähköpostin tai puhelinnumeron.",
  "details.empty": "Ei vielä tietoja. Aloita sähköpostiosoitteestasi.",
  "details.remove": "Poista",
  "details.removeConfirm": "Poistetaanko tämä tieto ({kind}) ja kaikki sille löydetyt tulokset?",
  "details.codePlaceholder": "6-numeroinen koodi",
  "details.codeLabel": "Vahvistuskoodi: {value}",
  "details.verify": "Vahvista",
  "details.resend": "Lähetä uusi koodi",
  "details.codeSent": "Uusi koodi on matkalla.",
  "details.consoleHint": "Paikallinen palvelin: koodi tulostuu API:n lokiin.",
  "details.addTitle": "Lisää tieto",
  "details.kindLabel": "Tyyppi",
  "details.valueLabel": "Arvo",
  "details.optEmail": "Sähköposti",
  "details.optPhone": "Puhelin",
  "details.optName": "Koko nimi",
  "details.optUsername": "Käyttäjänimi",
  "details.add": "Lisää",
  "details.addAndSend": "Lisää ja lähetä koodi",
  "details.attestUsername": "Tämä käyttäjänimi on minun. Seuraavaksi todistan sen profiilini esittelytekstiin lisättävällä koodilla.",
  "details.attestName": "Tämä nimi on minun. Ymmärrän, ettei Footprint voi tarkistaa sitä ja luottaa sanaani.",
  "ph.email": "sinä@esimerkki.fi",
  "ph.phone": "+358 40 123 4567",
  "ph.name": "Etunimi Sukunimi",
  "ph.username": "kayttajanimi",
  "ph.city": "Kaupunki, jossa asut tai olet asunut",
  "ph.birth_year": "1990",
  "ph.workplace": "Työnantaja tai oppilaitos",

  "context.title": "Erotu samannimisistä",
  "context.intro":
    "Monella on sama nimi. Kaupunki, syntymävuosi tai työpaikka auttaa skannausta pitämään sinua koskevat tulokset ja jättämään pois muita koskevat. Näitä tietoja käytetään vain vertailuun. Niitä ei koskaan haeta sellaisenaan.",
  "context.detailLabel": "Tieto",
  "context.valueLabel": "Tiedon arvo",
  "context.optCity": "Kaupunki",
  "context.optBirthYear": "Syntymävuosi",
  "context.optWorkplace": "Työpaikka tai oppilaitos",

  "photo.title": "Lisää kuva itsestäsi",
  "photo.intro": "Tekaistujen profiilien tarkistus käyttää kuvaa etsiessään profiileja, joissa kuvaasi käytetään.",
  "photo.noReverse": " Käänteistä kuvahakua ei ole vielä otettu käyttöön tällä palvelimella.",
  "photo.label": "Kuva",
  "photo.upload": "Lataa",
  "photo.attest": "Kuvassa olen minä.",

  "proof.instructions":
    "Lisää tämä koodi {platform}-profiilisi esittelytekstiin, tallenna ja tarkista. Voit poistaa koodin vahvistuksen jälkeen.",
  "proof.copy": "Kopioi",
  "proof.open": "Avaa {platform}",
  "proof.check": "Tarkista profiilini",
  "proof.checking": "Tarkistetaan…",
  "proof.newCode": "Hae uusi koodi",
  "proof.required": "Ei käytetä skannauksissa ennen kuin todistat sen omaksesi:",
  "proof.optional": "Todista omaksesi:",
  "proof.getCode": "Hae koodi",
  "proof.platformLabel": "Palvelu, jossa {value} todistetaan",

  "cat.data_broker": "Tietovälittäjä",
  "cat.people_search": "Henkilöhakupalvelu",
  "cat.social_profile": "Someprofiili",
  "cat.possible_impersonation": "Mahdollinen tekaistu profiili",
  "cat.paste_or_leak": "Vuoto- tai liitesivusto",
  "cat.news_or_public_record": "Uutinen tai julkinen rekisteri",
  "cat.other": "Muu",
  "scanKind.exposure": "Skannaus",
  "scanKind.impersonation": "Tekaistujen profiilien tarkistus",
  "scanStatus.queued": "jonossa",
  "scanStatus.running": "käynnissä",
  "scanStatus.completed": "valmis",
  "scanStatus.failed": "epäonnistui",
  "scanStatus.refused": "keskeytetty",

  "scan.title": "Tarkista digitaalinen jalanjälkesi",
  "scan.intro":
    "Skannaus etsii lisäämiäsi tietoja julkisesta verkosta, tietovälittäjiltä ja henkilöhakupalveluista. Se voi kestää muutaman minuutin. Voit poistua sivulta; tulokset tallentuvat tilillesi.",
  "scan.contextTip":
    "Vinkki: lisää Omat tiedot -kohtaan kaupunki, syntymävuosi tai työpaikka. Skannaus jättää niiden avulla pois ihmiset, joilla on vain sama nimi.",
  "scan.start": "Skannaa jalanjälkeni",
  "scan.impersonation": "Etsi tekaistuja profiileja",
  "scan.reason.verify": "Vahvista ensin sähköposti tai puhelin.",
  "scan.reason.notConfigured": "Skannausta ei ole määritetty tällä palvelimella (malli tai verkkohaku puuttuu).",
  "scan.reason.profile": "Lisää ensin nimesi, käyttäjänimi tai kuva.",
  "scan.limits": "Enintään {n} skannausta päivässä, yksi kerrallaan.",
  "scan.earlier": "Aiemmat skannaukset",
  "scan.view": "Näytä",
  "scan.scanning": "Skannataan…",
  "scan.progress": "Haetaan. Sivu päivittyy itsestään.",
  "scan.leftOutOne":
    "Jätettiin pois 1 tulos, joka koskee samannimistä henkilöä. Se oli ristiriidassa tietojesi kanssa, eikä sitä tallennettu.",
  "scan.leftOutMany":
    "Jätettiin pois {n} tulosta, jotka koskevat samannimisiä henkilöitä. Ne olivat ristiriidassa tietojesi kanssa, eikä niitä tallennettu.",
  "scan.nothing": "Tässä skannauksessa ei löytynyt tietojasi.",
  "scan.aboutYou": "Sinusta",
  "scan.maybeOthers": "Voi olla samanniminen henkilö",
  "scan.reviewHint":
    "Vain nimesi yhdistää nämä sinuun. Vahvistamillesi tulee poisto-ohjeet. Muut poistetaan, eikä niitä näytetä tulevissa skannauksissa.",
  "scan.thisIsMe": "Tämä olen minä",
  "scan.notMe": "En ole minä",
  "scan.seePlan": "Katso, mitä näille voi tehdä",
  "scan.confirmed": "Vahvistit tämän",
  "conf.high": "varma",
  "conf.medium": "melko varma",
  "conf.low": "epävarma",
  "usage.model": "Mallikutsut",
  "usage.tools": "Työkalukutsut",
  "usage.tokens": "Tokenit",
  "trace.title": "Näin skannaus eteni",
  "trace.intro":
    "Jokainen malli- ja työkalukutsu tuloksineen, kestoineen ja tokenmäärineen. Jäljissä ei koskaan ole tietojasi eikä sivujen sisältöä.",
  "trace.step": "Vaihe",
  "trace.outcome": "Tulos",
  "trace.start": "Alku",
  "trace.took": "Kesto",
  "trace.tokens": "Tokenit sisään / ulos",
  "trace.model": "Malli",

  "breach.title": "Onko sähköpostisi tietomurrossa?",
  "breach.intro": "Hakee vahvistetut sähköpostiosoitteesi Have I Been Pwned -palvelusta. Vain vahvistamasi osoitteet lähetetään.",
  "breach.checking": "Tarkistetaan…",
  "breach.check": "Tarkista vahvistetut sähköpostini",
  "breach.notConfigured": "Tietomurtohakuja ei ole määritetty tällä palvelimella (HIBP-avain puuttuu).",
  "breach.none": "Tunnettuja tietomurtoja ei löytynyt vahvistetuille sähköposteillesi ({n} tarkistettu).",
  "breach.passwords": "Salasanoja vuotanut",
  "breach.inPlan": "Jokainen tietomurto on nyt kohta toimintasuunnitelmassasi.",
  "pw.title": "Onko salasana vuotanut?",
  "pw.intro":
    "Salasanasi ei koskaan lähde selaimesta. Se tiivistetään täällä, ja vain tiivisteen viisi ensimmäistä merkkiä lähetetään. Vertailu tehdään omalla laitteellasi.",
  "pw.placeholder": "Käyttämäsi salasana",
  "pw.label": "Tarkistettava salasana",
  "pw.check": "Tarkista",
  "pw.seen": "Nähty tietomurroissa {n} kertaa. Lopeta sen käyttö ja vaihda se kaikkialla, missä olet käyttänyt sitä.",
  "pw.notFound": "Ei löytynyt tunnetuista tietomurroista. Se ei tee siitä vahvaa, vain tuntemattoman.",
  "pw.sent": "Palvelimelle lähetettiin: {prefix}",

  "jur.FI": "Suomi",
  "jur.EU": "EU / ETA",
  "jur.US-CA": "Kalifornia",
  "jur.US": "Muualla Yhdysvalloissa",
  "jur.OTHER": "Muualla",
  "prio.0": "Tee tämä ensin",
  "prio.1": "Tärkeä",
  "prio.2": "Kannattaa tehdä",
  "prio.3": "Kun ehdit",
  "item.open": "Tekemättä",
  "item.sent": "Pyyntö lähetetty",
  "item.done": "Tehty",
  "item.dismissed": "Ei koske minua",
  "plan.title": "Toimintasuunnitelmasi",
  "plan.liveIn": "Asuinmaa",
  "plan.intro":
    "Koottu skannauksistasi ja tietomurtotarkistuksistasi. Asuinmaasi ratkaisee, mihin lakiin kirjeet viittaavat. Mitään ei lähetetä puolestasi. Poistopyynnöt lähetät itse, ja jotkin palvelut pyytävät todistamaan henkilöllisyytesi.",
  "plan.progress": "{done}/{total} tehty",
  "plan.building": "Suunnitelmaa laaditaan…",
  "plan.openOptOut": "Avaa poistosivu",
  "plan.openPage": "Avaa sivu",
  "plan.letter": "Poistopyyntökirje",
  "plan.copyLetter": "Kopioi kirje",
  "plan.copied": "Kopioitu",
  "plan.statusLabel": "Tila: {title}",

  "account.title": "Tili",
  "account.signedInAs": "Kirjautunut",
  "account.since": "Jäsen alkaen",
  "account.eraseTitle": "Poista tilini",
  "account.eraseBody":
    "Poistaa tilisi, kaikki lisäämäsi tiedot, skannaukset ja löydökset, tietomurtotulokset ja toimintasuunnitelmasi. Poistoa ei voi perua. Tietoturvan vuoksi säilytetään loki toiminnoista; siinä on vain tunnisteita eikä tietojasi.",
  "account.confirmWord": "poista",
  "account.typeToConfirm": "Vahvista kirjoittamalla ”{word}”",
  "account.eraseButton": "Poista kaikki",
};

const MESSAGES: Record<Lang, Record<MessageKey, string>> = { en, fi };
const STORAGE_KEY = "footprint.lang";

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "en" || saved === "fi") return saved;
  } catch {
    // Storage blocked: fall back to the browser language.
  }
  return navigator.language?.toLowerCase().startsWith("fi") ? "fi" : "en";
}

export type Translate = (key: MessageKey, values?: Record<string, string | number>) => string;

interface I18n {
  lang: Lang;
  setLang: (lang: Lang) => void;
  t: Translate;
}

const I18nContext = createContext<I18n | null>(null);

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const setLang = useCallback((next: Lang) => {
    setLangState(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not persisted; the choice still holds for this page load.
    }
  }, []);

  const t = useCallback<Translate>(
    (key, values) => {
      let text = MESSAGES[lang][key] ?? en[key] ?? key;
      for (const [name, value] of Object.entries(values ?? {})) text = text.replaceAll(`{${name}}`, String(value));
      return text;
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside <I18nProvider>");
  return value;
}
