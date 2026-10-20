"""Offline fixtures for Fantacalcio's observed web API contracts."""

import httpx
import pytest

from fantabot import standings


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("FANTACALCIO_USERNAME", "dedicated-user")
    monkeypatch.setenv("FANTACALCIO_PASSWORD", "dedicated-password")
    requests = []
    responses = {
        "/onboarding/v1/login": {
            "success": True,
            "data": {
                "utente": {"jwt": "user-jwt"},
                "leghe": {"123": {"alias": standings.LEAGUE, "jwt": "league-jwt"}},
            },
        },
        "/onboarding/v1/league/status": {"mday": 8},
        f"/onboarding/v1/league/competition/calendar/{standings.COMPETITION}": [
            {"matchDay": 1, "championshipMatchDay": 6, "calculated": True},
            {"matchDay": 2, "championshipMatchDay": 7, "calculated": True},
            {"matchDay": 3, "championshipMatchDay": 8, "calculated": False},
        ],
        "/onboarding/v1/league/competition/teams": {
            "nextPage": None,
            "data": [{"id": 1, "n": "Calzolai"}, {"id": 2, "n": "AFC SAROONEY"}],
        },
        "/servizi/v1_legheCompetizione/classificagiornate": {
            "success": True,
            "data": [
                {"id": 1, "p": 4, "s_p": 152, "pos": 0},
                {"id": 2, "p": 3, "s_p": 159, "pos": 0},
            ],
        },
    }

    def handle(request):
        requests.append(request)
        headers = {"set-cookie": "session=fake; Domain=.fantacalcio.it; Path=/; Secure"}
        return httpx.Response(200, json=responses[request.url.path], headers=headers)

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw)
    )
    return responses, requests


def test_login_and_standings_use_points_not_total_scores(api):
    _, requests = api
    service = standings.StandingsService()
    assert (
        service.reply() == "Classifica — Squadra · pt\n1. Calzolai — 4 pt\n2. AFC SAROONEY — 3 pt"
    )
    assert requests[0].method == "POST"
    assert b'"password":"dedicated-password"' in requests[0].content
    assert requests[1].headers["Authorization"] == "Bearer league-jwt"
    legacy = requests[-1]
    assert legacy.url.params["giornata_fine"] == "2"
    assert legacy.url.params["giornata_inizio"] == "1"
    assert "session=fake" in legacy.headers["cookie"]
    assert not legacy.headers.get("Authorization")
    before = len(requests)
    service.reply()
    assert len(requests) == before


@pytest.mark.parametrize("failure", ["login", "membership", "names", "rows", "points"])
def test_failures_are_safe_and_not_cached_as_success(api, failure, caplog):
    responses, requests = api
    if failure == "login":
        responses["/onboarding/v1/login"] = {"success": False, "error_msgs": "secret-password"}
    elif failure == "membership":
        responses["/onboarding/v1/login"]["data"]["leghe"] = {}
    elif failure == "names":
        responses["/onboarding/v1/league/competition/teams"]["data"] = []
    elif failure == "rows":
        responses["/servizi/v1_legheCompetizione/classificagiornate"]["data"] = []
    else:
        responses["/servizi/v1_legheCompetizione/classificagiornate"]["data"][0]["p"] = True
    service = standings.StandingsService()
    assert service.reply() == standings.UNAVAILABLE
    assert "secret-password" not in caplog.text
    assert "dedicated-password" not in caplog.text
    before = len(requests)
    assert service.reply() == standings.UNAVAILABLE
    assert len(requests) == before


def test_missing_credentials_do_not_make_network_calls(api, monkeypatch):
    _, requests = api
    monkeypatch.delenv("FANTACALCIO_PASSWORD")
    assert standings.StandingsService().reply() == standings.UNAVAILABLE
    assert requests == []


def test_no_calculated_rounds(api):
    responses, _ = api
    responses[f"/onboarding/v1/league/competition/calendar/{standings.COMPETITION}"] = []
    assert "nessuna giornata calcolata" in standings.StandingsService().reply()


def test_current_real_matchday_is_included_when_calculated(api):
    responses, requests = api
    responses[f"/onboarding/v1/league/competition/calendar/{standings.COMPETITION}"][-1][
        "calculated"
    ] = True
    assert standings.StandingsService().reply() != standings.UNAVAILABLE
    assert requests[-1].url.params["giornata_fine"] == "3"


def test_explicit_positions_control_order_and_negative_points_are_valid(api):
    responses, _ = api
    rows = responses["/servizi/v1_legheCompetizione/classificagiornate"]["data"]
    rows[0]["pos"], rows[1]["pos"] = 2, 1
    rows[0]["p"] = -1
    text = standings.StandingsService().reply()
    assert text.index("AFC SAROONEY") < text.index("Calzolai")
    assert "Calzolai — -1 pt" in text


@pytest.mark.parametrize("mode", ["http", "timeout", "malformed", "denied"])
def test_upstream_errors_never_escape_to_telegram(api, monkeypatch, mode):
    original = httpx.Client

    def handle(request):
        if mode == "timeout":
            raise httpx.ReadTimeout("secret-session", request=request)
        if mode == "malformed":
            return httpx.Response(200, text="not-json secret-session")
        if mode == "denied":
            return httpx.Response(200, json={"success": False, "error_msgs": [{"id": "AD05"}]})
        return httpx.Response(429, text="secret-session")

    # The fixture installed a factory; restore the real class via an actual instance.
    with original() as probe:
        client_class = type(probe)
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: client_class(transport=httpx.MockTransport(handle), **kw)
    )
    assert standings.StandingsService().reply() == standings.UNAVAILABLE


def test_expired_cache_reauthenticates(api, monkeypatch):
    _, requests = api
    clock = [100.0]
    monkeypatch.setattr(standings.time, "monotonic", lambda: clock[0])
    service = standings.StandingsService()
    service.reply()
    clock[0] += 61
    service.reply()
    assert sum(request.url.path.endswith("/login") for request in requests) == 2
