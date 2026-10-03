"""API glue: validation, plan shape and caching (team loading and the solver are stubbed)."""

from types import SimpleNamespace

import pandas as pd
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from midweek_merchant import api  # noqa: E402
from midweek_merchant.team.reconstruct import TeamState  # noqa: E402


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    proj = pd.DataFrame({"gw": [6, 7, 8], "element": [1, 1, 1]})
    monkeypatch.setattr(api.store, "get", lambda: (proj, "2026-10-03T16:28:52+00:00"))
    calls: list[dict] = []

    def fake_state(settings, team_id, overrides=None):  # noqa: ANN001, ANN202
        if team_id == 404:
            raise RuntimeError("not found")
        return TeamState(team_id, "Test", 6, squad=[], bank=5, free_transfers=1, chips_available={})

    def fake_plan(settings, state, proj, **kw):  # noqa: ANN001, ANN202
        calls.append(kw)
        return SimpleNamespace(status="Optimal", objective=1.0, total_xpts=99.5, weeks=[object()])

    monkeypatch.setattr(api.service, "team_state", fake_state)
    monkeypatch.setattr(api.service, "plan_for_team", fake_plan)
    monkeypatch.setattr(api.service, "plan_table", lambda p, proj: [{"gw": 6}])
    api._cache.clear()
    c = TestClient(api.app)
    c.calls = calls  # type: ignore[attr-defined]
    return c


def test_plan_ok_and_cached(client: TestClient) -> None:
    body = {"team_id": 7, "horizon": 8, "roll": True, "max_hits": 1, "locks": [3]}
    r = client.post("/api/plan", json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"]["entry_id"] == 7 and out["weeks"] == [{"gw": 6}] and out["total_xpts"] == 99.5
    kw = client.calls[0]  # type: ignore[attr-defined]
    assert kw["horizon"] == 3  # capped at the projected gameweeks
    assert kw["no_transfer_gws"] == {6} and kw["max_hits_per_gw"] == 1 and kw["locked"] == {3}
    assert client.post("/api/plan", json=body).json() == out
    assert len(client.calls) == 1  # type: ignore[attr-defined]  # second request served from cache


def test_plan_errors(client: TestClient) -> None:
    assert client.post("/api/plan", json={"team_id": 404}).status_code == 404
    assert client.post("/api/plan", json={"team_id": 7, "horizon": 9}).status_code == 422
    assert client.post("/api/plan", json={"team_id": 0}).status_code == 422
