import json

from fantabot.observability import log_chat_error


class ProviderError(Exception):
    status_code = 429
    request_id = "provider-request-123"

    def __init__(self, body):
        super().__init__("Provider request failed")
        self.body = body


def event(caplog):
    return json.loads(
        next(record.message for record in caplog.records if record.name == "fantabot.chat")
    )


def test_logs_provider_details_but_redacts_secrets_and_prompt_text(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-api-key")
    prompt = "La mia domanda privata"
    exc = ProviderError(
        {
            "error": {
                "message": f"Rate limit for secret-api-key while handling {prompt}",
                "code": 429,
                "metadata": {
                    "provider_name": "ExampleProvider",
                    "raw": json.dumps(
                        {
                            "error": {"message": "Upstream capacity exceeded"},
                            "request": {"authorization": "must-not-be-logged"},
                        }
                    ),
                },
            }
        }
    )
    log_chat_error(exc, model="qwen/test", request_id="private-room-123", prompt_contents=[prompt])
    logged = event(caplog)
    assert logged["message"] == "Rate limit for [REDACTED] while handling [REDACTED]"
    assert logged["provider"] == "ExampleProvider"
    assert logged["http_status"] == 429
    assert logged["error_code"] == "429"
    assert logged["provider_request_id"] == "provider-request-123"
    assert logged["upstream_message"] == "Upstream capacity exceeded"
    assert len(logged["request_ref"]) == 12
    for value in ("secret-api-key", prompt, "must-not-be-logged", "private-room-123"):
        assert value not in caplog.text


def test_traceback_reports_locations_not_exception_body_or_source(caplog):
    try:
        raise RuntimeError("Useful error summary")
    except RuntimeError as exc:
        log_chat_error(exc, model="qwen/test", request_id="id", prompt_contents=[])
    logged = event(caplog)
    assert logged["error_type"] == "RuntimeError"
    assert logged["message"] == "Useful error summary"
    assert any("test_observability.py:" in frame for frame in logged["traceback_locations"])
    assert all("raise RuntimeError" not in frame for frame in logged["traceback_locations"])


def test_json_escaped_prompt_and_token_patterns_are_redacted(caplog):
    prompt = "Città\nprivata"
    escaped_prompt = json.dumps(prompt, ensure_ascii=True)[1:-1]
    token = "123456789:" + "A" * 30
    exc = ProviderError({"message": f"Rejected {escaped_prompt}, sk-or-v1-fakekey and {token}"})
    log_chat_error(exc, model="qwen/test", request_id="id", prompt_contents=[prompt])
    assert event(caplog)["message"] == "Rejected [REDACTED], [REDACTED] and [REDACTED]"


def test_non_json_upstream_body_is_not_dumped(caplog):
    exc = ProviderError({"message": "Provider error", "metadata": {"raw": "private raw body"}})
    log_chat_error(exc, model="qwen/test", request_id="id", prompt_contents=[])
    assert "private raw body" not in caplog.text
    assert "upstream_message" not in event(caplog)


def test_missing_message_does_not_dump_provider_body(caplog):
    exc = ProviderError({"headers": {"Authorization": "private-header"}})
    log_chat_error(exc, model="qwen/test", request_id="id", prompt_contents=[])
    assert event(caplog)["message"] == "No provider error message available"
    assert "private-header" not in caplog.text
