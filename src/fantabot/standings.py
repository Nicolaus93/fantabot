"""Read-only adapter for the Fantacalcio web APIs; no model inference."""

import json
import logging
import os
import time

import httpx

API = "https://apileague.fantacalcio.it/onboarding/v1"
LEGACY = "https://leghe.fantacalcio.it/servizi/v1_legheCompetizione/classificagiornate"
LEAGUE = "fantacalcio-a-casaccio"
COMPETITION = 867709
# Public application identifier shipped in Fantacalcio's production web client.
APP_KEY = "ICiELOObd5DF5uJEATi77CRvHiiRuMU0"
# The web login rejects HTTPX's default identity or requests without this Origin.
WEB_HEADERS = {
    "app_key": APP_KEY,
    "Accept": "application/json",
    "Origin": "https://leghe.fantacalcio.it",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}
UNAVAILABLE = "Classifica al momento non disponibile. Riprova tra poco."
REQUEST_STAGES = {
    "/onboarding/v1/login": "login",
    f"/onboarding/v1/league/competition/calendar/{COMPETITION}": "calendar",
    "/onboarding/v1/league/status": "status",
    "/onboarding/v1/league/competition/teams": "teams",
    "/servizi/v1_legheCompetizione/classificagiornate": "standings",
}


# Only code-shaped identifiers are allowed out of an authentication response.
SAFE_ERROR_CODES = frozenset(
    [f"ATH{i:03}" for i in range(100)]
    + [f"AD{i:02}" for i in range(100)]
    + [f"S{i:03}" for i in range(100)]
)


def _error_codes(response):
    """Extract bounded, allowlisted identifiers, never descriptions or user data."""
    if len(response.content) > 16384:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    candidates = [payload.get("code"), payload.get("errorCode"), payload.get("error_code")]
    error = payload.get("error")
    if isinstance(error, dict):
        candidates.append(error.get("code"))
    errors = payload.get("error_msgs")
    if isinstance(errors, list):
        candidates.extend(item.get("id") for item in errors[:20] if isinstance(item, dict))
    return sorted(
        {code for code in candidates if isinstance(code, str) and code in SAFE_ERROR_CODES}
    )[:5]


def _json(response):
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict) and payload.get("success") is False:
        raise ValueError("Fantacalcio rejected request")
    return payload


def _login(client, username, password):
    payload = _json(client.post(f"{API}/login", json={"username": username, "password": password}))
    data = payload.get("data", payload)
    leagues = data["leghe"]
    league_jwt = next(league["jwt"] for league in leagues.values() if league["alias"] == LEAGUE)
    if not isinstance(league_jwt, str) or not league_jwt:
        raise ValueError("Missing Fantacalcio league session")
    # Login establishes the legacy cookies; keep them only in this client's memory.
    client.headers["Authorization"] = f"Bearer {league_jwt}"


def _team_names(client):
    names = {}
    for page in range(1, 6):
        payload = _json(
            client.get(
                f"{API}/league/competition/teams",
                params={
                    "page": page,
                    "pageSize": 50,
                    "competitionId": COMPETITION,
                },
            )
        )
        for team in payload["data"]:
            name = team["n"]
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                raise ValueError("Invalid team name")
            names[team["id"]] = " ".join(name.split())
        if not payload.get("nextPage"):
            return names
    raise ValueError("Too many teams")


def _standings_text(client):
    calendar = _json(client.get(f"{API}/league/competition/calendar/{COMPETITION}"))
    status = _json(client.get(f"{API}/league/status"))
    calculated = [
        round_["matchDay"]
        for round_ in calendar
        if round_.get("calculated") is True and round_["championshipMatchDay"] <= status["mday"]
    ]
    if not calculated:
        return "Classifica non ancora disponibile: nessuna giornata calcolata."
    names = _team_names(client)
    # Legacy requests use cookies, not the league Bearer token.
    response = client.get(
        LEGACY,
        params={
            "alias_lega": LEAGUE,
            "id_competizione": COMPETITION,
            "giornata_inizio": 1,
            "giornata_fine": max(calculated),
        },
        headers={"Authorization": ""},
    )
    rows = _json(response)["data"]
    if not isinstance(rows, list) or not rows or len(rows) != len(names):
        raise ValueError("Incomplete standings")
    if all(isinstance(row.get("pos"), int) and row["pos"] > 0 for row in rows):
        rows = sorted(rows, key=lambda row: row["pos"])
    lines = ["Classifica — Squadra · pt"]
    seen = set()
    for row in rows:
        team_id, points = row["id"], row["p"]
        if team_id in seen or not isinstance(points, int) or isinstance(points, bool):
            raise ValueError("Invalid standings")
        seen.add(team_id)
        lines.append(f"{len(seen)}. {names[team_id]} — {points} pt")
    text = "\n".join(lines)
    if len(text) > 3900:
        raise ValueError("Standings exceed Telegram text limit")
    return text


class StandingsService:
    """Serial-worker cache avoids logging in for each repeated command."""

    def __init__(self):
        self._text = UNAVAILABLE
        self._expires = 0.0

    def reply(self):
        now = time.monotonic()
        if now < self._expires:
            return self._text
        diagnostics: dict[str, str | int | bool | list[str] | None] = {
            "stage": "configuration",
            "http_status": None,
            "json_response": None,
        }

        def track_request(request):
            diagnostics.update(
                stage=REQUEST_STAGES.get(request.url.path, "unknown"),
                http_status=None,
                json_response=None,
            )

        def track_response(response):
            diagnostics.update(
                http_status=response.status_code,
                json_response="json" in response.headers.get("content-type", "").lower(),
            )

        try:
            username = os.environ["FANTACALCIO_USERNAME"]
            password = os.environ["FANTACALCIO_PASSWORD"]
            if not username or not password:
                raise ValueError("Missing Fantacalcio credentials")
            with httpx.Client(
                timeout=10,
                headers=WEB_HEADERS,
                event_hooks={"request": [track_request], "response": [track_response]},
            ) as client:
                _login(client, username, password)
                self._text = _standings_text(client)
            self._expires = time.monotonic() + 60
        except Exception as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                diagnostics["error_codes"] = _error_codes(exc.response)
            # Never log response bodies, credentials, cookies or JWTs.
            logging.warning(
                json.dumps(
                    {
                        "event": "fantacalcio.standings.failed",
                        "error_type": type(exc).__name__,
                        **diagnostics,
                    }
                )
            )
            self._text = UNAVAILABLE
            self._expires = time.monotonic() + 30
        return self._text
