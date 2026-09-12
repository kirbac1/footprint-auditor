from conftest import add_name, add_verified_email, login, reply, text, tool_use

from exposure_auditor.tools.search import SearchResult

FINDER = "https://www.finder.fi/Maija+Meik%C3%A4l%C3%A4inen/Helsinki/123"
SPOKEO = "https://www.spokeo.com/Maija-Meikalainen/p1"


def _scan_with(ctx, headers, name_id, city_id, results, language="en"):
    ctx.search.results = results
    records = [
        tool_use(f"r{i}", "record_finding", {
            "result_id": f"r{i}", "category": "people_search", "matched_identifier_ids": [name_id, city_id],
            "conflicting_identifier_ids": [], "confidence": "high", "rationale": "Nimi ja kaupunki täsmäävät.",
        })
        for i in range(1, len(results) + 1)
    ]
    ctx.llm.script += [
        reply("tool_use", tool_use("s", "search_web", {"query": "Maija Meikäläinen", "site": ""})),
        reply("tool_use", *records),
        reply("end_turn", text("valmis")),
    ]
    r = ctx.client.post(f"/scan?language={language}", headers=headers)
    assert r.status_code == 202, r.text


def _setup(ctx):
    headers = login(ctx.client)
    add_verified_email(ctx, headers)
    name = add_name(ctx, headers)
    city = ctx.client.post(
        "/identifiers", json={"kind": "city", "value": "Helsinki", "attest": True}, headers=headers
    ).json()
    return headers, name["id"], city["id"]


def test_finnish_plan_with_letters_that_follow_the_recipient(ctx):
    headers, name_id, city_id = _setup(ctx)
    _scan_with(ctx, headers, name_id, city_id, [
        SearchResult(FINDER, "Maija Meikäläinen, Helsinki", "Puhelinnumero ja osoite"),
        SearchResult(SPOKEO, "Maija Meikäläinen, Helsinki", "Phone and address history"),
    ])

    items = ctx.client.post("/remediation-plan?jurisdiction=FI&language=fi", headers=headers).json()["items"]
    by_title = {i["title"]: i for i in items}

    fonecta = by_title["Poista tietosi palvelusta Fonecta (Finder.fi)"]
    assert "operaattorin" in fonecta["detail"]
    assert fonecta["draft"].startswith("[Tarkista ennen lähettämistä") and "17 artikla" in fonecta["draft"]

    # A US broker gets the English letter even in a Finnish plan.
    spokeo = by_title["Poista tietosi palvelusta Spokeo"]
    assert "Article 17" in spokeo["draft"] and "Tarkista" not in spokeo["draft"]

    dvv = by_title["Kiellä tietojesi luovuttaminen väestötietojärjestelmästä"]
    assert dvv["url"] == "https://dvv.fi/tietojen-luovuttamisen-kieltaminen"
    assert any(t.startswith("Pyydä puhelinoperaattoriasi") for t in by_title)

    english = ctx.client.post("/remediation-plan?jurisdiction=FI&language=en", headers=headers).json()["items"]
    titles = [i["title"] for i in english]
    assert "Opt out of Fonecta (Finder.fi)" in titles
    assert any(i["url"] == "https://dvv.fi/en/non-disclosure-of-personal-data" for i in english)


def test_scan_language_reaches_the_agent(ctx):
    headers, name_id, city_id = _setup(ctx)
    _scan_with(ctx, headers, name_id, city_id, [SearchResult(SPOKEO, "Maija Meikäläinen, Helsinki", "")], "fi")
    assert "write each rationale and your final summary in Finnish" in ctx.llm.calls[0]["messages"][0]["content"]


def test_unknown_language_is_rejected(ctx):
    headers = login(ctx.client)
    assert ctx.client.post("/remediation-plan?language=sv", headers=headers).status_code == 422
