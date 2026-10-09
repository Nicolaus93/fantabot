import httpx
import pytest

from fantabot.setup_webhook import register_webhook


def test_registers_only_message_updates_and_verifies_identity():
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path.endswith("getMe"):
            return httpx.Response(200, json={"ok": True, "result": {"username": "FantaBot"}})
        return httpx.Response(200, json={"ok": True, "result": True})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        register_webhook(client, "123:fake", "fantabot", "https://example.modal.run/", "secret")
    import json

    assert len(calls) == 2
    payload = json.loads(calls[1].content)
    assert payload == {
        "url": "https://example.modal.run/telegram/webhook",
        "secret_token": "secret",
        "allowed_updates": ["message"],
        "drop_pending_updates": True,
        "max_connections": 2,
    }


def test_identity_mismatch_does_not_register_webhook():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"username": "OtherBot"}})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="does not match"):
            register_webhook(client, "123:fake", "fantabot", "https://example.modal.run", "secret")
    assert len(calls) == 1


@pytest.mark.parametrize("url", ["http://example.com", "https://example.com?key=a", "not-a-url"])
def test_invalid_url_does_not_make_network_request(url):
    def unexpected(request):
        pytest.fail("Invalid URL should be rejected before any network request")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        with pytest.raises(ValueError, match="HTTPS base URL"):
            register_webhook(client, "123:fake", "fantabot", url, "secret")
