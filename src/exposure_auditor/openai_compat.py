"""Models that speak the OpenAI chat-completions API: Ollama on this machine,
or a hosted service like Mistral behind the same shape.

The agent and every guard are written against the Anthropic message shape, so
this translates in both directions rather than touching the orchestrator:
tools and messages on the way out, tool calls and usage on the way back. What
Anthropic offers and this doesn't is prompt caching and thinking effort; both
are dropped here, which costs tokens on a hosted provider and nothing locally.

Raw HTTP rather than the openai SDK: one endpoint, no streaming, one less
dependency, and Ollama serves this shape natively.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx2

log = logging.getLogger(__name__)

# finish_reason -> the stop_reason the agent loop already understands.
_STOP_REASONS = {
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "refusal",
}


class ModelUnavailable(RuntimeError):
    """The provider could not be reached or refused the request."""


@dataclass(frozen=True)
class TextBlock:
    text: str
    type: str = "text"


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass(frozen=True)
class Message:
    content: list[Any] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)
    role: str = "assistant"


def _tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
                "strict": bool(t.get("strict")),
            },
        }
        for t in tools
    ]


def _assistant_message(blocks: list[Any]) -> dict:
    """Our own blocks from a previous turn, back into OpenAI's shape."""
    text, calls = [], []
    for b in blocks:
        kind = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
        if kind == "text":
            text.append(b["text"] if isinstance(b, dict) else b.text)
        elif kind == "tool_use":
            block_id = b["id"] if isinstance(b, dict) else b.id
            name = b["name"] if isinstance(b, dict) else b.name
            args = b["input"] if isinstance(b, dict) else b.input
            calls.append(
                {
                    "id": block_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
                }
            )
    out: dict[str, Any] = {"role": "assistant", "content": "\n".join(text)}
    if calls:
        out["tool_calls"] = calls
    return out


def _messages(system: str | None, messages: list[dict]) -> list[dict]:
    out: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        content = m["content"]
        if m["role"] == "assistant":
            out.append(_assistant_message(content if isinstance(content, list) else [content]))
            continue
        if isinstance(content, str):
            out.append({"role": "user", "content": content})
            continue
        # A user turn carrying tool results becomes one "tool" message each:
        # OpenAI pairs every result with the call id that produced it.
        text = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": str(b.get("content", ""))})
            elif isinstance(b, dict) and b.get("type") == "text":
                text.append(b["text"])
        if text:
            out.append({"role": "user", "content": "\n".join(text)})
    return out


def _blocks(message: dict) -> list[Any]:
    blocks: list[Any] = []
    if text := (message.get("content") or "").strip():
        blocks.append(TextBlock(text))
    for call in message.get("tool_calls") or []:
        fn = call.get("function", {})
        raw = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else dict(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            # Leave it empty: the tool's own guard rejects it and the model is
            # told why, which is the same path any other bad call takes.
            log.warning("model returned unparseable tool arguments for %s", fn.get("name"))
            args = {}
        blocks.append(ToolUseBlock(id=str(call.get("id") or ""), name=str(fn.get("name") or ""), input=args))
    return blocks


def _usage(raw: dict) -> Usage:
    details = raw.get("prompt_tokens_details") or {}
    return Usage(
        input_tokens=int(raw.get("prompt_tokens") or 0),
        output_tokens=int(raw.get("completion_tokens") or 0),
        cache_read_input_tokens=int(details.get("cached_tokens") or 0),
    )


class OpenAICompatLLM:
    """Exposes `.messages.create(...)`, like the Anthropic client does."""

    def __init__(self, http: httpx2.AsyncClient, base_url: str, api_key: str | None, provider: str) -> None:
        self._http = http
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self.provider = provider
        self.messages = self

    async def create(self, **kwargs: Any) -> Message:
        payload = {
            "model": kwargs["model"],
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": _messages(kwargs.get("system"), kwargs.get("messages", [])),
        }
        if tools := _tools(kwargs.get("tools")):
            payload["tools"] = tools
        # cache_control and output_config are Anthropic-only; dropping them
        # changes cost and reasoning depth, never the agent's guards.
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        try:
            r = await self._http.post(self._url, json=payload, headers=headers)
        except Exception as exc:
            raise ModelUnavailable(f"{self.provider}: {type(exc).__name__}") from exc
        if r.status_code != 200:
            raise ModelUnavailable(f"{self.provider} returned HTTP {r.status_code}")
        body = r.json()
        choices = body.get("choices") or []
        if not choices:
            raise ModelUnavailable(f"{self.provider} returned no choices")
        choice = choices[0]
        return Message(
            content=_blocks(choice.get("message") or {}),
            stop_reason=_STOP_REASONS.get(str(choice.get("finish_reason")), "end_turn"),
            usage=_usage(body.get("usage") or {}),
        )
