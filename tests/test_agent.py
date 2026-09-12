import pytest
from conftest import FakeSearch, ScriptedLLM, reply, text, tool_use

from exposure_auditor.agent.orchestrator import AgentConfig, ScanAgent
from exposure_auditor.agent.scope import ScopedIdentifier, ScopeGuard, ToolError
from exposure_auditor.config import Settings
from exposure_auditor.tools.brokers import BrokerRegistry

IDS = [
    ScopedIdentifier("e1", "email", "maija@example.com"),
    ScopedIdentifier("p1", "phone", "+358401234567"),
    ScopedIdentifier("n1", "name", "Maija Meikäläinen"),
]


@pytest.mark.parametrize("query", [
    '"Maija Meikäläinen" Helsinki',
    "MAIJA MEIKÄLÄINEN",
    "maija@example.com",
    "040 123 4567",
    "+358-40-123-4567",
])
def test_scope_guard_accepts_in_scope_queries(query):
    ScopeGuard(IDS).check_query(query)


@pytest.mark.parametrize("query", [
    "Jane Doe Helsinki",
    '"Maija Meikäläinen" OR "Jane Doe"',
    "Maija Meikäläinen | Jane Doe",
    "Maija",
    "",
])
def test_scope_guard_rejects_out_of_scope_queries(query):
    with pytest.raises(ToolError):
        ScopeGuard(IDS).check_query(query)


@pytest.mark.parametrize(
    "query",
    [
        "Kirbac Ugur",              # the parts, in the other order
        "Uğur Kırbaç",              # how the name is actually spelled
        "ugur-kirbac profile",      # as a URL slug
        "UGUR KIRBAC site:spokeo.com",
    ],
)
def test_a_name_is_in_scope_however_it_is_written(query):
    """A Turkish or Finnish name reaches the guard spelled several ways. It is
    the same person each time, and refusing the accented spelling would refuse
    the one the web actually indexes."""
    guard = ScopeGuard([ScopedIdentifier("n1", "name", "Ugur Kirbac")])
    guard.check_query(query)


@pytest.mark.parametrize("query", ["Kirbac Tampere", "Ugur Helsinki", "Maija Meikalainen"])
def test_part_of_a_name_is_not_in_scope(query):
    """Every part has to be there: a surname on its own is half a phone book,
    and a first name with a city is somebody else's search."""
    guard = ScopeGuard([ScopedIdentifier("n1", "name", "Ugur Kirbac")])
    with pytest.raises(ToolError) as exc:
        guard.check_query(query)
    assert exc.value.code == "out_of_scope"


def test_a_rejection_says_what_would_be_accepted():
    # The model has to be able to fix the query; a refusal it can't act on
    # gets repeated until the scan runs out.
    guard = ScopeGuard([ScopedIdentifier("n1", "name", "Ugur Kirbac")])
    with pytest.raises(ToolError, match="Ugur Kirbac"):
        guard.check_query("data broker removal")


def test_scope_guard_site_must_be_a_domain():
    assert ScopeGuard.check_site("https://www.Spokeo.com/") == "www.spokeo.com"
    with pytest.raises(ToolError):
        ScopeGuard.check_site("spokeo.com OR evil")


def _config(llm, max_turns=5):
    return AgentConfig(
        llm=llm, model_id="anthropic.claude-opus-5", effort="high", max_turns=max_turns,
        max_searches=10, search=FakeSearch(), reverse_image=None, brokers=BrokerRegistry.load(),
    )


async def test_refusal_ends_scan_as_refused():
    agent = ScanAgent(_config(ScriptedLLM([reply("refusal")])), "exposure", IDS)
    outcome = await agent.run()
    assert outcome.status == "refused" and outcome.findings == []


async def test_turn_limit():
    looping = [reply("tool_use", tool_use(f"t{i}", "search_web", {"query": "Maija Meikäläinen", "site": ""})) for i in range(3)]
    outcome = await ScanAgent(_config(ScriptedLLM(looping), max_turns=3), "exposure", IDS).run()
    assert outcome.status == "turn_limit"


async def test_reverse_image_unavailable_is_reported_not_crashed():
    llm = ScriptedLLM([
        reply("tool_use", tool_use("t1", "reverse_image_search", {"identifier_id": "i1"})),
        reply("end_turn", text("Reverse-image search was not available.")),
    ])
    ids = IDS + [ScopedIdentifier("i1", "image", "profile photo")]
    agent = ScanAgent(_config(llm), "impersonation", ids, images={"i1": b"\x89PNG..."})
    outcome = await agent.run()
    assert outcome.status == "completed"
    result = llm.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True and "not configured" in result["content"]
    assert "reverse_image_search" in llm.calls[0]["messages"][0]["content"]  # told up front


def test_prod_refuses_console_code_delivery():
    with pytest.raises(ValueError, match="console"):
        Settings(
            _env_file=None, env="prod", database_url="postgresql+asyncpg://db/x",
            jwt_secret="s", field_encryption_key="k", blind_index_key="b",
        )
