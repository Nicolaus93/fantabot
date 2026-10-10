import httpx
import pytest

from fantabot.get_group_id import main


def mock_telegram(monkeypatch, data):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake-secret")
    requests = []
    original_client = httpx.Client

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=data)

    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    return requests


def test_prints_unique_groups_and_ignores_private_chats(monkeypatch, capsys):
    group = {"message": {"chat": {"id": -100123, "title": "Fanta", "type": "supergroup"}}}
    requests = mock_telegram(
        monkeypatch,
        {
            "ok": True,
            "result": [group, group, {"message": {"chat": {"id": 42, "type": "private"}}}],
        },
    )
    main()
    assert capsys.readouterr().out == "Fanta: TELEGRAM_GROUP_ID=-100123\n"
    assert len(requests) == 1
    assert requests[0].url.path.endswith("/getUpdates")
    assert "offset" not in requests[0].url.params


def test_empty_updates_explain_how_to_trigger_group_message(monkeypatch, capsys):
    mock_telegram(monkeypatch, {"ok": True, "result": []})
    main()
    assert "/ask@YourBotUsername" in capsys.readouterr().out


def test_active_webhook_is_reported_without_disabling_it(monkeypatch):
    requests = mock_telegram(monkeypatch, {"ok": False, "error_code": 409})
    with pytest.raises(SystemExit, match="does not change your webhook"):
        main()
    assert len(requests) == 1


def test_missing_token_is_reported_before_network_access(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="Set TELEGRAM_BOT_TOKEN"):
        main()


def test_transport_errors_do_not_expose_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:fake-secret")

    def fail(**kwargs):
        raise httpx.ConnectError("Error at https://api.telegram.org/bot123:fake-secret/getUpdates")

    monkeypatch.setattr(httpx, "Client", fail)
    with pytest.raises(SystemExit) as error:
        main()
    assert "ConnectError" in str(error.value)
    assert "fake-secret" not in str(error.value)
