import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from fantabot.chat import ChatService, bounded_history, cost_units
from fantabot.config import Settings
from fantabot.state import State, euro_units, month_key

NOW = datetime(2026, 1, 15, tzinfo=timezone.utc).timestamp()


class FakeProvider:
    def __init__(self, *, usage=(10, 5), error=None, on_call=None):
        self.usage = usage
        self.error = error
        self.on_call = on_call
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        if self.on_call:
            self.on_call()
        if self.error:
            raise self.error
        return "Schiererei il primo, se titolare.", self.usage


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr("fantabot.state.time.time", lambda: NOW)
    value = State(tmp_path / "chat.sqlite3")
    yield value
    value.db.close()


def test_reservation_is_persisted_before_provider_then_refunded_to_actual_cost(tmp_path):
    settings = Settings()
    events = []
    state = State(tmp_path / "chat.sqlite3", persist=lambda: events.append("persist"))

    def on_call():
        assert state.spent_eur(month_key(NOW)) > 0
        assert events == ["persist", "persist"]
        events.append("provider")

    provider = FakeProvider(on_call=on_call)
    service = ChatService(state, provider, settings)
    result = service.chat("one", "room", "alice", "Chi schiero?", now=NOW)
    assert result["status"] == "ok"
    assert events == ["persist", "persist", "provider", "persist"]
    assert state.spent_eur("2026-01") == Decimal(cost_units(settings, 10, 5)) / 1_000_000_000
    state.db.close()


@pytest.mark.parametrize("usage,error", [(None, None), ((10, 5), TimeoutError("uncertain"))])
def test_uncertain_or_missing_usage_retains_full_reservation(state, usage, error):
    settings = Settings()
    before_provider = []
    provider = FakeProvider(
        usage=usage,
        error=error,
        on_call=lambda: before_provider.append(state.spent_eur("2026-01")),
    )
    service = ChatService(state, provider, settings)
    result = service.chat("one", "room", "alice", "Chi schiero?", now=NOW)
    assert result["status"] == ("error" if error else "ok")
    assert state.spent_eur("2026-01") == before_provider[0] > 0
    repeated = service.chat("one", "room", "alice", "Chi schiero?", now=NOW + 30)
    assert repeated == result
    assert len(provider.calls) == 1
    if error:
        assert state.history("room", NOW) == []


def test_budget_limit_blocks_provider_without_spending_more(state):
    settings = replace(Settings(), monthly_budget_eur=Decimal("0.000001"))
    provider = FakeProvider()
    service = ChatService(state, provider, settings)
    assert service.chat("one", "room", "alice", "Chi schiero?", now=NOW)["status"] == "budget"
    assert provider.calls == []
    assert state.spent_eur("2026-01") == 0


def test_budget_history_and_idempotency_survive_reopening_database(tmp_path, monkeypatch):
    monkeypatch.setattr("fantabot.state.time.time", lambda: NOW)
    path = tmp_path / "chat.sqlite3"
    state = State(path)
    provider = FakeProvider()
    result = ChatService(state, provider, Settings()).chat("one", "room", "alice", "ciao", NOW)
    spent = state.spent_eur("2026-01")
    state.db.close()
    reopened = State(path)
    second_provider = FakeProvider()
    service = ChatService(reopened, second_provider, Settings())
    assert service.chat("one", "room", "alice", "ciao", NOW + 30) == result
    assert second_provider.calls == []
    assert reopened.spent_eur("2026-01") == spent
    assert reopened.history("room", NOW)[-1]["content"] == result["text"]
    reopened.db.close()


def test_utc_calendar_month_gets_new_allowance_without_resetting_previous_spend(state):
    settings = replace(Settings(), monthly_budget_eur=Decimal("1"))
    jan_end = datetime(2026, 1, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp()
    feb_start = jan_end + 1
    assert (
        state.reserve("one", "hash1", "alice", euro_units(Decimal("1")), settings, jan_end) is None
    )
    refused = state.reserve("two", "hash2", "bob", 1, settings, jan_end)
    assert refused["status"] == "budget"
    assert (
        state.reserve("three", "hash3", "bob", euro_units(Decimal("1")), settings, feb_start)
        is None
    )
    assert state.spent_eur("2026-01") == state.spent_eur("2026-02") == Decimal("1")


def test_cooldown_is_per_user_and_idempotent_retries_do_not_hit_it(state):
    provider = FakeProvider()
    service = ChatService(state, provider, Settings())
    first = service.chat("one", "room", "alice", "ciao", NOW)
    assert service.chat("one", "room", "alice", "ciao", NOW + 1) == first
    assert service.chat("two", "room", "alice", "altro", NOW + 1)["status"] == "cooldown"
    assert service.chat("three", "room", "bob", "altro", NOW + 1)["status"] == "ok"
    assert service.chat("four", "room", "alice", "altro", NOW + 15)["status"] == "ok"
    assert len(provider.calls) == 3


@pytest.mark.parametrize(
    ("room", "user", "text"),
    [("room", "alice", "different"), ("other", "alice", "ciao"), ("room", "bob", "ciao")],
)
def test_request_id_reuse_with_changed_payload_conflicts_without_call(state, room, user, text):
    provider = FakeProvider()
    service = ChatService(state, provider, Settings())
    service.chat("one", "room", "alice", "ciao", NOW)
    assert service.chat("one", room, user, text, NOW + 30)["status"] == "conflict"
    assert len(provider.calls) == 1


def test_unfinished_request_survives_restart_and_is_not_rebilled(tmp_path):
    path = tmp_path / "chat.sqlite3"
    state = State(path)
    settings = Settings()
    assert state.reserve("one", "hash", "alice", 100, settings, NOW) is None
    state.db.close()
    reopened = State(path)
    assert reopened.previous("one", "hash")["status"] == "pending"
    assert reopened.reserve("one", "hash", "alice", 100, settings, NOW + 30)["status"] == "pending"
    assert reopened.spent_eur("2026-01") == Decimal("0.0000001")
    reopened.db.close()


def test_delivery_claims_survive_restart_and_suppress_duplicates(tmp_path):
    path = tmp_path / "chat.sqlite3"
    state = State(path)
    assert state.claim_delivery(99, NOW)
    assert not state.claim_delivery(99, NOW + 10)
    state.db.close()
    reopened = State(path)
    assert not reopened.claim_delivery(99, NOW + 30)
    assert reopened.claim_delivery(100, NOW + 30)
    reopened.db.close()


def test_history_is_bounded_by_messages_and_retains_whole_turn_pairs(state):
    settings = Settings()
    provider = FakeProvider()
    service = ChatService(state, provider, settings)
    for i in range(10):
        service.chat(str(i), "room", "alice", f"domanda {i}", NOW + i * 20)
    history = state.history("room", NOW + 200)
    assert len(history) == settings.history_messages
    assert history[0]["role"] == "user"
    assert history[-1]["role"] == "assistant"
    assert [m["content"] for m in history if m["role"] == "user"] == [
        f"domanda {i}" for i in range(4, 10)
    ]


def test_history_is_bounded_by_utf8_bytes_without_orphan_assistant_turns():
    settings = replace(Settings(), history_bytes=1000)
    history = [
        {"role": role, "content": "é" * 150} for _ in range(6) for role in ("user", "assistant")
    ]
    bounded = bounded_history(history, settings)
    assert 0 < len(bounded) < len(history)
    assert len(json.dumps(bounded, ensure_ascii=False).encode()) <= settings.history_bytes
    assert len(bounded) % 2 == 0
    assert bounded[0]["role"] == "user"


def test_conversation_history_is_isolated_and_expires(state):
    provider = FakeProvider()
    service = ChatService(state, provider, Settings())
    service.chat("one", "topic:1", "alice", "prima domanda", NOW)
    service.chat("two", "topic:2", "alice", "seconda domanda", NOW + 20)
    assert [m["content"] for m in provider.calls[1] if m["role"] == "user"] == ["seconda domanda"]
    assert state.history("topic:1", NOW + 7 * 86400 + 1) == []
    service.chat("three", "topic:1", "alice", "ultima domanda", NOW + 40)
    assert [m["content"] for m in provider.calls[2] if m["role"] == "user"] == [
        "prima domanda",
        "ultima domanda",
    ]


@pytest.mark.parametrize("text", ["", "   ", "x" * 4001])
def test_invalid_input_never_calls_provider_or_spends(state, text):
    provider = FakeProvider()
    service = ChatService(state, provider, Settings())
    assert service.chat("one", "room", "alice", text, NOW)["status"] == "invalid"
    assert provider.calls == []
    assert state.spent_eur("2026-01") == 0


@pytest.mark.parametrize("budget", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_invalid_budget_configuration_is_rejected(budget):
    with pytest.raises(ValueError):
        replace(Settings(), monthly_budget_eur=budget)


def test_changing_model_requires_explicit_prices(monkeypatch):
    monkeypatch.setenv("CHAT_MODEL", "some-other-model")
    monkeypatch.delenv("INPUT_USD_PER_MILLION", raising=False)
    monkeypatch.delenv("OUTPUT_USD_PER_MILLION", raising=False)
    with pytest.raises(ValueError, match="both token prices"):
        Settings.from_env()
    monkeypatch.setenv("INPUT_USD_PER_MILLION", "1")
    monkeypatch.setenv("OUTPUT_USD_PER_MILLION", "2")
    assert Settings.from_env().model == "some-other-model"
