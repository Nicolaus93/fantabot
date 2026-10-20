import json

import pytest

from fantabot import test_fantacalcio_standings as diagnostic


@pytest.mark.parametrize("available", [True, False])
def test_local_standings_diagnostic_prints_only_availability(monkeypatch, capsys, available):
    monkeypatch.setattr(
        diagnostic.StandingsService,
        "reply",
        lambda self: "private-team-data" if available else diagnostic.UNAVAILABLE,
    )
    assert diagnostic.main() == (0 if available else 1)
    output = capsys.readouterr().out
    assert json.loads(output) == {"standings_available": available}
    assert "private-team-data" not in output
