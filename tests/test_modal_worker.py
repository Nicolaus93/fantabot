"""Exercise Modal's local method lifecycle without credentials or a mounted volume."""

import httpx
import pytest

from fantabot import chat, modal_app, state


@pytest.fixture
def local_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "FantaBot")
    monkeypatch.setenv("TELEGRAM_GROUP_ID", "-100")
    monkeypatch.setenv("CHAT_API_KEY", "a" * 32)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "b" * 32)
    real_state = state.State
    databases = []
    provider_calls = []
    deliveries = []

    def local_state(path, persist):
        database = real_state(tmp_path / "chat.sqlite3")
        databases.append(database)
        return database

    class Provider:
        def complete(self, messages):
            provider_calls.append(messages)
            return "Ciao!", (20, 3)

    monkeypatch.setattr(state, "State", local_state)
    monkeypatch.setattr(chat, "OpenRouterProvider", lambda api_key, settings: Provider())
    original_client = httpx.Client

    def deliver(request):
        deliveries.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(deliver), **kwargs),
    )
    yield modal_app.ChatWorker(), provider_calls, deliveries
    for database in databases:
        database.db.close()


def update(update_id=1, chat_id=-100):
    return {
        "update_id": update_id,
        "message": {
            "message_id": 5,
            "chat": {"id": chat_id, "type": "supergroup"},
            "from": {"id": 7, "is_bot": False},
            "text": "/ask Ciao",
        },
    }


def test_local_web_factory_initializes_with_configured_secrets(local_worker):
    from fastapi.testclient import TestClient

    app = modal_app.web.local()
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.post("/chat", json={}).status_code == 401


def test_local_chat_lifecycle_uses_persistent_core(local_worker):
    worker, calls, deliveries = local_worker
    result = worker.chat.local("api:1", "api:room", "api:user", "Ciao")
    assert result == {"status": "ok", "text": "Ciao!"}
    assert len(calls) == 1
    assert deliveries == []


def test_duplicate_telegram_jobs_send_and_bill_only_once(local_worker):
    worker, calls, deliveries = local_worker
    worker.telegram.local(update())
    worker.telegram.local(update())
    assert len(calls) == 1
    assert len(deliveries) == 1


def test_worker_checks_group_even_if_called_without_web_layer(local_worker):
    worker, calls, deliveries = local_worker
    worker.telegram.local(update(chat_id=-999))
    assert calls == []
    assert deliveries == []
