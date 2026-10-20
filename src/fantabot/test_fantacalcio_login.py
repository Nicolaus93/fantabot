"""Local, opt-in login diagnostic. Never prints credentials or response values."""

import json
import os

import httpx

from fantabot.standings import API, APP_KEY, LEAGUE, _error_codes

# Only these literal field names can appear in output; unknown keys may contain PII.
FIELDS = frozenset(
    {
        "data",
        "utente",
        "leghe",
        "success",
        "state",
        "error",
        "errors",
        "error_msgs",
        "code",
        "id",
        "errorCode",
        "error_code",
        "message",
        "detail",
        "descrizione",
        "jwt",
        "token_auth",
    }
)


def _structure(value, depth=0):
    if isinstance(value, dict):
        result = {"type": "object", "fields": {}}
        if depth < 3:
            result["fields"] = {
                key: _structure(value[key], depth + 1) for key in sorted(FIELDS.intersection(value))
            }
        result["unknown_field_count"] = len(value.keys() - FIELDS)
        return result
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    return {"type": "string"}


def main():
    username = os.getenv("FANTACALCIO_USERNAME")
    password = os.getenv("FANTACALCIO_PASSWORD")
    if not username or not password:
        print(
            json.dumps(
                {"error": "Set FANTACALCIO_USERNAME and FANTACALCIO_PASSWORD in the environment"}
            )
        )
        return 1
    # Disable HTTP request logging even if this entry point is invoked in a configured process.
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        with httpx.Client(
            timeout=10, headers={"app_key": APP_KEY, "Accept": "application/json"}
        ) as client:
            response = client.post(
                f"{API}/login", json={"username": username, "password": password}
            )
    except httpx.HTTPError as exc:
        print(json.dumps({"stage": "login", "error_type": type(exc).__name__}))
        return 1
    report = {
        "stage": "login",
        "http_status": response.status_code,
        "error_codes": _error_codes(response),
        "json_response": "json" in response.headers.get("content-type", "").lower(),
        "league_session_returned": False,
    }
    try:
        payload = response.json()
    except ValueError:
        report["response_structure"] = {"type": "non-json"}
    else:
        report["response_structure"] = _structure(payload)
        if isinstance(payload, dict) and payload.get("success") is not False:
            data = payload.get("data", payload)
            leagues = data.get("leghe", {}) if isinstance(data, dict) else {}
            if isinstance(leagues, dict):
                report["league_session_returned"] = any(
                    isinstance(league, dict)
                    and league.get("alias") == LEAGUE
                    and isinstance(league.get("jwt"), str)
                    and bool(league["jwt"])
                    for league in leagues.values()
                )
    print(json.dumps(report, sort_keys=True))
    return 0 if response.is_success and report["league_session_returned"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
