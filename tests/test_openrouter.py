"""Real SDK requests against an offline transport: never call OpenAI/OpenRouter."""

import json
from decimal import Decimal
from typing import Any, TypedDict

import httpx
import openai
import pytest

from fantabot.chat import ChatService, OpenRouterProvider
from fantabot.config import DEFAULT_MODEL, Settings
from fantabot.state import State, month_key


class SDKResponse(TypedDict):
    status: int
    json: dict[str, Any]


@pytest.fixture
def sdk_transport(monkeypatch):
    requests = []
    client_options = []
    response: SDKResponse = {
        "status": 200,
        "json": {
            "id": "generation-fake",
            "object": "chat.completion",
            "created": 1,
            "model": DEFAULT_MODEL,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "Ciao!"},
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        },
    }
    clients = []
    original_sdk = openai.OpenAI

    def handle(request):
        requests.append(request)
        return httpx.Response(response["status"], json=response["json"])

    def sdk_client(**kwargs):
        client_options.append(kwargs)
        client = original_sdk(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )
        clients.append(client)
        return client

    monkeypatch.setattr(openai, "OpenAI", sdk_client)
    yield requests, client_options, response
    for client in clients:
        client.close()


def test_sdk_targets_openrouter_and_sends_price_limited_non_reasoning_request(sdk_transport):
    requests, options, _ = sdk_transport
    provider = OpenRouterProvider("fake-openrouter-key", Settings())
    result = provider.complete([{"role": "user", "content": "Ciao"}])
    assert result == ("Ciao!", (100, 20))
    assert len(requests) == 1
    assert str(requests[0].url) == "https://openrouter.ai/api/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer fake-openrouter-key"
    assert options[0]["max_retries"] == 0
    assert options[0]["timeout"] == 30
    payload = json.loads(requests[0].content)
    assert payload["model"] == "qwen/qwen3-30b-a3b-instruct-2507"
    assert payload["max_tokens"] == 512
    assert "max_completion_tokens" not in payload
    assert "reasoning" not in payload
    assert payload["provider"] == {
        "sort": "price",
        "require_parameters": True,
        "allow_fallbacks": True,
        "max_price": {"prompt": 0.10, "completion": 0.30},
    }


@pytest.mark.parametrize("status", [429, 503])
def test_openrouter_failure_does_not_retry(sdk_transport, status):
    requests, _, response = sdk_transport
    response.update(status=status, json={"error": {"message": "No provider available"}})
    with pytest.raises(openai.APIStatusError):
        OpenRouterProvider("fake", Settings()).complete([{"role": "user", "content": "Ciao"}])
    assert len(requests) == 1


def test_rate_limit_reply_and_logs_are_useful_without_leaking_details(
    sdk_transport, tmp_path, caplog
):
    requests, _, response = sdk_transport
    response.update(status=429, json={"error": {"message": "private-provider-detail"}})
    settings = Settings()
    state = State(tmp_path / "state.sqlite3")
    service = ChatService(state, OpenRouterProvider("private-key", settings), settings)
    now = 1767225600
    result = service.chat("request", "room", "user", "private-user-message", now=now)
    assert result["status"] == "error"
    assert "occupato" in result["text"]
    event = json.loads(next(r.message for r in caplog.records if r.name == "fantabot.chat"))
    assert event["error_type"] == "RateLimitError"
    assert event["http_status"] == 429
    assert event["message"] == "private-provider-detail"
    assert "private-key" not in caplog.text
    assert "private-user-message" not in caplog.text
    assert len(requests) == 1
    assert state.spent_eur(month_key(now)) > 0  # Conservative failure reservation is retained.
    state.db.close()


def test_empty_completion_is_not_treated_as_success(sdk_transport):
    _, _, response = sdk_transport
    response["json"]["choices"][0]["message"]["content"] = None
    with pytest.raises(ValueError, match="No text completion"):
        OpenRouterProvider("fake", Settings()).complete([{"role": "user", "content": "Ciao"}])


def test_missing_usage_preserves_unknown_cost(sdk_transport):
    _, _, response = sdk_transport
    response["json"].pop("usage")
    assert OpenRouterProvider("fake", Settings()).complete([]) == ("Ciao!", None)


def test_default_environment_selects_qwen_and_matching_prices(monkeypatch):
    for key in ("CHAT_MODEL", "INPUT_USD_PER_MILLION", "OUTPUT_USD_PER_MILLION"):
        monkeypatch.delenv(key, raising=False)
    settings = Settings.from_env()
    assert settings.model == DEFAULT_MODEL
    assert settings.input_usd_per_million == Decimal("0.10")
    assert settings.output_usd_per_million == Decimal("0.30")
