import json

import httpx
import pytest

from fantabot import test_fantacalcio_login as diagnostic


@pytest.mark.parametrize("status,success", [(200, True), (403, False)])
def test_diagnostic_reports_structure_without_values(monkeypatch, capsys, status, success):
    monkeypatch.setenv("FANTACALCIO_USERNAME", "private-user")
    monkeypatch.setenv("FANTACALCIO_PASSWORD", "private-password")
    original = httpx.Client
    calls = []

    def handle(request):
        calls.append(request)
        assert request.headers["Origin"] == "https://leghe.fantacalcio.it"
        assert request.headers["User-Agent"] == diagnostic.WEB_HEADERS["User-Agent"]
        assert json.loads(request.content) == {
            "username": "private-user",
            "password": "private-password",
        }
        return httpx.Response(
            status,
            json={
                "success": success,
                "data": {
                    "leghe": {"private-key": {"alias": diagnostic.LEAGUE, "jwt": "private-jwt"}}
                },
                "detail": "private-password",
                "private-user": "private-cookie",
            },
            headers={"set-cookie": "private-cookie"},
        )

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    assert diagnostic.main() == (0 if success else 1)
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["http_status"] == status
    assert report["league_session_returned"] is success
    assert report["response_structure"]["fields"]["detail"] == {"type": "string"}
    assert len(calls) == 1
    for private in (
        "private-user",
        "private-password",
        "private-key",
        "private-jwt",
        "private-cookie",
    ):
        assert private not in output


def test_missing_credentials_fail_before_any_http(monkeypatch, capsys):
    monkeypatch.delenv("FANTACALCIO_USERNAME", raising=False)
    monkeypatch.delenv("FANTACALCIO_PASSWORD", raising=False)
    monkeypatch.setattr(httpx, "Client", lambda **kw: pytest.fail("Network must not be called"))
    assert diagnostic.main() == 1
    assert "FANTACALCIO_USERNAME" in capsys.readouterr().out


@pytest.mark.parametrize("mode", ["timeout", "html"])
def test_network_and_non_json_failures_are_safe(monkeypatch, capsys, mode):
    monkeypatch.setenv("FANTACALCIO_USERNAME", "fake")
    monkeypatch.setenv("FANTACALCIO_PASSWORD", "private-password")
    original = httpx.Client

    def handle(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("private-password", request=request)
        return httpx.Response(403, text="private-password", headers={"content-type": "text/html"})

    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    assert diagnostic.main() == 1
    output = capsys.readouterr().out
    assert "private-password" not in output
    assert json.loads(output)["stage"] == "login"
