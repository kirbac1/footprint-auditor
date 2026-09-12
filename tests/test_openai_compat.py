"""The adapter that lets the agent run on a model that isn't Claude.

The guards are written against the Anthropic message shape, so everything the
agent relies on has to survive the round trip: tool definitions out, tool calls
back, and usage in the fields the trace records.
"""

import json
from types import SimpleNamespace

import pytest

from exposure_auditor.agent.orchestrator import RECORD_TOOL, SEARCH_TOOL
from exposure_auditor.openai_compat import ModelUnavailable, OpenAICompatLLM, TextBlock, ToolUseBlock


class _FakeHttp:
    """Records the request and replies with a canned chat completion."""

    def __init__(self, body: dict | None = None, status_code: int = 200, raises: Exception | None = None) -> None:
        self.body = body or _completion()
        self.status_code = status_code
        self.raises = raises
        self.sent: dict = {}

    async def post(self, url, json=None, headers=None):
        if self.raises:
            raise self.raises
        self.sent = {"url": url, "json": json, "headers": headers}
        return SimpleNamespace(status_code=self.status_code, json=lambda: self.body)


def _completion(content="", tool_calls=None, finish_reason="tool_calls", usage=None):
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 193, "completion_tokens": 33, "prompt_tokens_details": {"cached_tokens": 7}},
    }


def _call(name="search_web", arguments='{"query":"Maija Meikalainen Helsinki","site":""}', call_id="call_1"):
    return [{"id": call_id, "type": "function", "function": {"name": name, "arguments": arguments}}]


def _llm(http):
    return OpenAICompatLLM(http, "http://127.0.0.1:11434/v1", None, "ollama")


async def test_tool_calls_become_the_blocks_the_agent_expects():
    http = _FakeHttp(_completion(tool_calls=_call()))

    response = await _llm(http).messages.create(
        model="qwen3", max_tokens=100, system="you are", tools=[SEARCH_TOOL], messages=[{"role": "user", "content": "go"}]
    )

    assert response.stop_reason == "tool_use"
    block = response.content[0]
    assert isinstance(block, ToolUseBlock)
    assert block.name == "search_web"
    assert block.input == {"query": "Maija Meikalainen Helsinki", "site": ""}
    assert response.usage.input_tokens == 193
    assert response.usage.output_tokens == 33
    assert response.usage.cache_read_input_tokens == 7


async def test_tools_and_system_prompt_are_translated():
    http = _FakeHttp()
    await _llm(http).messages.create(
        model="qwen3",
        max_tokens=100,
        system="the system prompt",
        tools=[SEARCH_TOOL, RECORD_TOOL],
        messages=[{"role": "user", "content": "find me"}],
        # Anthropic-only knobs: accepted and dropped, never forwarded.
        cache_control={"type": "ephemeral"},
        output_config={"effort": "high"},
    )

    sent = http.sent["json"]
    assert sent["messages"][0] == {"role": "system", "content": "the system prompt"}
    assert sent["messages"][1] == {"role": "user", "content": "find me"}
    assert [t["function"]["name"] for t in sent["tools"]] == ["search_web", "record_finding"]
    assert sent["tools"][0]["function"]["parameters"] == SEARCH_TOOL["input_schema"]
    assert sent["tools"][0]["function"]["strict"] is True
    assert "cache_control" not in sent and "output_config" not in sent


async def test_a_tool_result_turn_is_paired_with_the_call_that_produced_it():
    http = _FakeHttp()
    await _llm(http).messages.create(
        model="qwen3",
        max_tokens=100,
        messages=[
            {"role": "user", "content": "find me"},
            {"role": "assistant", "content": [ToolUseBlock(id="call_1", name="search_web", input={"query": "maija"})]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "[]"}]},
        ],
    )

    assistant, result = http.sent["json"]["messages"][1], http.sent["json"]["messages"][2]
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"query": "maija"}
    assert result == {"role": "tool", "tool_call_id": "call_1", "content": "[]"}


async def test_text_only_answer_ends_the_scan():
    http = _FakeHttp(_completion(content="I found three listings.", finish_reason="stop"))

    response = await _llm(http).messages.create(model="qwen3", max_tokens=100, messages=[])

    assert response.stop_reason == "end_turn"
    assert response.content == [TextBlock("I found three listings.")]


async def test_a_filtered_answer_is_reported_as_a_refusal():
    http = _FakeHttp(_completion(finish_reason="content_filter"))

    response = await _llm(http).messages.create(model="qwen3", max_tokens=100, messages=[])

    assert response.stop_reason == "refusal"


async def test_unparseable_tool_arguments_reach_the_guard_not_a_crash():
    http = _FakeHttp(_completion(tool_calls=_call(arguments="{query: not json")))

    response = await _llm(http).messages.create(model="qwen3", max_tokens=100, messages=[])

    # An empty input is rejected by ScopeGuard, which tells the model why.
    assert response.content[0].input == {}


@pytest.mark.parametrize(
    "http",
    [_FakeHttp(status_code=500), _FakeHttp(raises=OSError("connection refused")), _FakeHttp({"choices": []})],
)
async def test_provider_trouble_is_an_operator_error(http):
    with pytest.raises(ModelUnavailable):
        await _llm(http).messages.create(model="qwen3", max_tokens=100, messages=[])


def test_a_local_model_is_not_billed_per_token(settings):
    from exposure_auditor.scans import cost_usd

    local = settings.model_copy(update={"llm_provider": "ollama"})
    assert cost_usd(local, 1_000_000, 1_000_000, 0, 0) == 0.0
    assert cost_usd(settings.model_copy(update={"llm_provider": "anthropic"}), 1_000_000, 0, 0, 0) > 0
