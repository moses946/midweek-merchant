"""HTTP API for the React dashboard's live features.

The dashboard renders the published JSON bundle on its own; this service adds what needs
Python at request time: rebuilding any FPL team from public data and solving its transfer
plan. Run it with ``uv run --extra api mm serve`` (or ``uvicorn midweek_merchant.api:app``).

The projections it plans on come from the local data directory, or from the published
``data`` branch when there is none; they are re-synced when the published forecast changes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from midweek_merchant import publish, service
from midweek_merchant.config import get_settings

log = logging.getLogger(__name__)

SYNC_EVERY_S = 30 * 60  # check the published bundle at most this often
MAX_CONCURRENT_SOLVES = int(os.environ.get("MM_MAX_SOLVES", "2"))


class PlanRequest(BaseModel):
    team_id: int = Field(gt=0, lt=100_000_000)
    horizon: int = Field(6, ge=1, le=8)
    decay: float = Field(0.85, ge=0.5, le=1.0)
    max_hits: int = Field(2, ge=0, le=3)
    roll: bool = False  # no transfers in the first gameweek
    locks: list[int] = Field(default_factory=list, max_length=15)
    bans: list[int] = Field(default_factory=list, max_length=50)


class _Store:
    """Projections in memory, refreshed from the published bundle when it changes."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.lock = threading.Lock()
        self.proj: pd.DataFrame | None = None
        self.generated_at: str | None = None
        self.checked = 0.0

    def _published_stamp(self) -> str | None:
        import httpx

        try:
            r = httpx.get(f"{publish.REMOTE_BASE}/outputs/forecast_meta.json", timeout=15)
            r.raise_for_status()
            return r.json().get("generated_at")
        except Exception:  # noqa: BLE001 - offline: keep serving what we have
            log.warning("could not reach the published bundle", exc_info=True)
            return None

    def get(self) -> tuple[pd.DataFrame, str]:
        with self.lock:
            s = self.settings
            meta_path = s.outputs_dir / "forecast_meta.json"
            now = time.monotonic()
            if self.proj is None or now - self.checked > SYNC_EVERY_S:
                self.checked = now
                local = json.loads(meta_path.read_text())["generated_at"] if meta_path.exists() else None
                remote = self._published_stamp() if os.environ.get("MM_SYNC", "1") == "1" else None
                if remote and remote != local:
                    publish.sync_from_remote(s)
                    local = remote
                if local is None:
                    raise HTTPException(503, "No forecast available yet")
                if self.proj is None or local != self.generated_at:
                    self.proj = service.load_projections(s)
                    self.generated_at = local
            assert self.proj is not None and self.generated_at is not None
            return self.proj, self.generated_at


store = _Store()
_solves = threading.BoundedSemaphore(MAX_CONCURRENT_SOLVES)
_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
_cache_lock = threading.Lock()

app = FastAPI(title="Midweek Merchant API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.environ.get("MM_CORS_ORIGINS", "*").split(",")],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    _, generated_at = store.get()
    return {"ok": True, "generated_at": generated_at}


@app.post("/api/plan")
def plan(req: PlanRequest) -> dict[str, Any]:
    """Rebuild a team from public FPL data and solve its transfer plan."""
    proj, generated_at = store.get()
    key = json.dumps({**req.model_dump(), "generated_at": generated_at}, sort_keys=True)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]

    s = store.settings
    try:
        state = service.team_state(s, req.team_id, overrides={})
    except Exception as exc:  # noqa: BLE001 - FPL returns 404 for unknown ids
        raise HTTPException(404, f"Could not load FPL team {req.team_id}") from exc
    gws = sorted(int(g) for g in proj["gw"].unique())
    if not _solves.acquire(timeout=20):
        raise HTTPException(429, "The solver is busy; try again in a few seconds")
    try:
        p = service.plan_for_team(
            s,
            state,
            proj,
            horizon=min(req.horizon, len(gws)),
            decay=req.decay,
            max_hits_per_gw=req.max_hits,
            locked=set(req.locks),
            banned=set(req.bans),
            no_transfer_gws={gws[0]} if req.roll else set(),
        )
    finally:
        _solves.release()
    if not p.weeks:
        raise HTTPException(422, f"No feasible plan ({p.status}); loosen locks or bans")
    out = {
        "state": state.to_dict(),
        "status": p.status,
        "objective": p.objective,
        "total_xpts": p.total_xpts,
        "weeks": service.plan_table(p, proj),
        "generated_at": generated_at,
    }
    with _cache_lock:
        _cache[key] = out
        while len(_cache) > 64:
            _cache.popitem(last=False)
    return out
