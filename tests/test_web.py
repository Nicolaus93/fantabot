from typing import Any, TypedDict

import pytest
from fastapi.testclient import TestClient

from fantabot.web import create_web_app

API_KEY = "api-" + "a" * 32
WEBHOOK_SECRET = "webhook-" + "b" * 32
GROUP_ID = -100123


def chat_payload(**overrides):
    value = {
        "request_id": "request-1",
        "conversation_id": "room",
        "user_id": "alice",
        "text": "Chi schiero?",
    }
    value.update(overrides)
    return value


def telegram_update(text="/ask Chi schiero?", group_id=GROUP_ID):
    return {
        "update_id": 100,
        "message": {
            "chat": {"id": group_id, "type": "supergroup"},
            "from": {"id": 42, "is_bot": False},
            "message_id": 10,
            "text": text,
        },
    }


class WorkerCalls(TypedDict):
    chat: list[tuple[str, ...]]
    telegram: list[dict[str, Any]]
    status: str
    failure: Exception | None


@pytest.fixture
def web_client():
    calls: WorkerCalls = {"chat": [], "telegram": [], "status": "ok", "failure": None}

    async def chat(*args):
        calls["chat"].append(args)
        if calls["failure"]:
            raise calls["failure"]
        return {"status": calls["status"], "text": "risposta"}

    async def enqueue(update):
        calls["telegram"].append(update)
        if calls["failure"]:
            raise calls["failure"]

    app = create_web_app(
        chat,
        enqueue,
        api_key=API_KEY,
        webhook_secret=WEBHOOK_SECRET,
        group_id=GROUP_ID,
        bot_username="Fantabot",
        bot_id=123456,
    )
    with TestClient(app) as client:
        yield client, calls


def test_health_is_public_and_does_not_dispatch(web_client):
    client, calls = web_client
    assert client.get("/health").json() == {"status": "ok"}
    assert calls["chat"] == calls["telegram"] == []


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", API_KEY, f"Basic {API_KEY}"])
def test_chat_authentication_precedes_validation_and_dispatch(web_client, authorization):
    client, calls = web_client
    headers = {"authorization": authorization} if authorization else {}
    response = client.post("/chat", headers=headers, content="not even valid JSON")
    assert response.status_code == 401
    assert calls["chat"] == []


def test_authenticated_chat_dispatches_namespaced_conversation_and_user(web_client):
    client, calls = web_client
    response = client.post(
        "/chat", headers={"authorization": f"Bearer {API_KEY}"}, json=chat_payload()
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "text": "risposta"}
    request_id, conversation, user, text = calls["chat"][0]
    assert request_id.startswith("api:")
    assert conversation == "api:room"
    assert user == "api:alice"
    assert text == "Chi schiero?"


def test_request_keys_cannot_collide_when_ids_contain_colons(web_client):
    client, calls = web_client
    headers = {"authorization": f"Bearer {API_KEY}"}
    client.post("/chat", headers=headers, json=chat_payload(conversation_id="a:b", request_id="c"))
    client.post("/chat", headers=headers, json=chat_payload(conversation_id="a", request_id="b:c"))
    assert calls["chat"][0][0] != calls["chat"][1][0]


@pytest.mark.parametrize(
    ("status", "http_status"),
    [
        ("invalid", 400),
        ("conflict", 409),
        ("pending", 409),
        ("cooldown", 429),
        ("budget", 503),
        ("error", 502),
    ],
)
def test_domain_refusals_have_meaningful_http_statuses(web_client, status, http_status):
    client, calls = web_client
    calls["status"] = status
    response = client.post(
        "/chat", headers={"authorization": f"Bearer {API_KEY}"}, json=chat_payload()
    )
    assert response.status_code == http_status
    assert response.json()["status"] == status


@pytest.mark.parametrize(
    "payload",
    [
        chat_payload(text="x" * 4001),
        chat_payload(text=42),
        chat_payload(user_id=""),
        chat_payload(conversation_id="has spaces"),
        chat_payload(extra="unexpected"),
    ],
)
def test_invalid_chat_payload_does_not_dispatch(web_client, payload):
    client, calls = web_client
    response = client.post("/chat", headers={"authorization": f"Bearer {API_KEY}"}, json=payload)
    assert response.status_code == 422
    assert calls["chat"] == []


@pytest.mark.parametrize("body", ["bad-json", "[]", '"string"'])
def test_bad_json_or_nonobject_body_is_rejected(web_client, body):
    client, calls = web_client
    response = client.post("/chat", headers={"authorization": f"Bearer {API_KEY}"}, content=body)
    assert response.status_code == 400
    assert calls["chat"] == []


@pytest.mark.parametrize("endpoint", ["/chat", "/telegram/webhook"])
def test_oversized_json_is_rejected_before_dispatch(web_client, endpoint):
    client, calls = web_client
    headers = (
        {"authorization": f"Bearer {API_KEY}"}
        if endpoint == "/chat"
        else {"x-telegram-bot-api-secret-token": WEBHOOK_SECRET}
    )
    response = client.post(endpoint, headers=headers, json={"text": "x" * 32769})
    assert response.status_code == 413
    assert calls["chat"] == calls["telegram"] == []


@pytest.mark.parametrize("secret", [None, "wrong", API_KEY])
def test_webhook_requires_its_own_secret_before_dispatch(web_client, secret):
    client, calls = web_client
    headers = {"x-telegram-bot-api-secret-token": secret} if secret else {}
    response = client.post("/telegram/webhook", headers=headers, json=telegram_update())
    assert response.status_code == 401
    assert calls["telegram"] == []


def test_valid_webhook_enqueues_without_waiting_for_chat_result(web_client):
    client, calls = web_client
    update = telegram_update()
    response = client.post(
        "/telegram/webhook",
        headers={"x-telegram-bot-api-secret-token": WEBHOOK_SECRET},
        json=update,
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls["telegram"] == [update]
    assert calls["chat"] == []


@pytest.mark.parametrize("update", [telegram_update(group_id=-100999), telegram_update("normale")])
def test_authenticated_but_irrelevant_webhook_is_acknowledged_without_enqueue(web_client, update):
    client, calls = web_client
    response = client.post(
        "/telegram/webhook",
        headers={"x-telegram-bot-api-secret-token": WEBHOOK_SECRET},
        json=update,
    )
    assert response.status_code == 200
    assert calls["telegram"] == []


def test_enqueue_failure_returns_retryable_status(web_client):
    client, calls = web_client
    calls["failure"] = RuntimeError("worker down")
    response = client.post(
        "/telegram/webhook",
        headers={"x-telegram-bot-api-secret-token": WEBHOOK_SECRET},
        json=telegram_update(),
    )
    assert response.status_code == 503


def test_chat_worker_failure_is_not_leaked_to_client(web_client):
    client, calls = web_client
    calls["failure"] = RuntimeError("sensitive provider details")
    response = client.post(
        "/chat", headers={"authorization": f"Bearer {API_KEY}"}, json=chat_payload()
    )
    assert response.status_code == 503
    assert "sensitive" not in response.text
