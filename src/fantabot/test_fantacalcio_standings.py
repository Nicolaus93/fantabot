"""Opt-in local login and standings diagnostic; reads environment, never .env."""

import json
import logging

from fantabot.standings import UNAVAILABLE, StandingsService


def main():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    text = StandingsService().reply()
    available = text != UNAVAILABLE
    print(json.dumps({"standings_available": available}))
    return 0 if available else 1


if __name__ == "__main__":
    raise SystemExit(main())
