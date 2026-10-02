"""Thin, polite client for the public Fantasy Premier League API."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api/"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36 midweek-merchant/0.1"
)


class FPLNotFound(Exception):
    """Raised for 404s (e.g. picks for a gameweek whose deadline has not passed)."""


class FPLClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        min_interval: float = 0.35,
        max_retries: int = 5,
        timeout: float = 30.0,
    ) -> None:
        self.cache_dir = cache_dir
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._last_call = 0.0
        self._http = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FPLClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ core
    def get(self, path: str, cache_key: str | None = None, max_age: float | None = None) -> Any:
        """GET ``path`` with throttling, retries and optional on-disk caching.

        ``max_age`` (seconds) allows serving a cached copy; ``None`` disables cache reads.
        """
        cache_file = self.cache_dir / f"{cache_key}.json" if (self.cache_dir and cache_key) else None
        fresh = (
            cache_file is not None
            and max_age is not None
            and cache_file.exists()
            and time.time() - cache_file.stat().st_mtime < max_age
        )
        if fresh:
            return json.loads(cache_file.read_text())

        delay = 2.0
        for attempt in range(1, self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                resp = self._http.get(path)
            except httpx.TransportError as exc:
                log.warning("FPL %s transport error (%s), attempt %d", path, exc, attempt)
            else:
                if resp.status_code == 404:
                    raise FPLNotFound(path)
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except ValueError:
                        # "The game is being updated." HTML/text pages around deadlines.
                        log.warning("FPL %s returned non-JSON body, attempt %d", path, attempt)
                    else:
                        if cache_file:
                            cache_file.parent.mkdir(parents=True, exist_ok=True)
                            cache_file.write_text(json.dumps(data))
                        return data
                else:
                    log.warning("FPL %s -> HTTP %d, attempt %d", path, resp.status_code, attempt)
            if attempt < self.max_retries:
                time.sleep(delay)
                delay *= 2
        if cache_file and cache_file.exists():
            log.warning("FPL %s failed; serving stale cache", path)
            return json.loads(cache_file.read_text())
        raise RuntimeError(f"FPL API request failed after {self.max_retries} attempts: {path}")

    # ------------------------------------------------------------------ endpoints
    def bootstrap(self, max_age: float | None = 300) -> dict[str, Any]:
        return self.get("bootstrap-static/", "bootstrap", max_age)

    def fixtures(self, max_age: float | None = 300) -> list[dict[str, Any]]:
        return self.get("fixtures/", "fixtures", max_age)

    def event_live(self, gw: int, max_age: float | None = None) -> dict[str, Any]:
        return self.get(f"event/{gw}/live/", f"live/event_{gw:02d}", max_age)

    def event_status(self) -> dict[str, Any]:
        return self.get("event-status/")

    def element_summary(self, element_id: int, max_age: float | None = 3600) -> dict[str, Any]:
        return self.get(f"element-summary/{element_id}/", f"elements/{element_id}", max_age)

    def entry(self, entry_id: int, max_age: float | None = 300) -> dict[str, Any]:
        return self.get(f"entry/{entry_id}/", f"entries/{entry_id}/entry", max_age)

    def entry_history(self, entry_id: int, max_age: float | None = 300) -> dict[str, Any]:
        return self.get(f"entry/{entry_id}/history/", f"entries/{entry_id}/history", max_age)

    def entry_transfers(self, entry_id: int, max_age: float | None = 300) -> list[dict[str, Any]]:
        return self.get(f"entry/{entry_id}/transfers/", f"entries/{entry_id}/transfers", max_age)

    def entry_picks(self, entry_id: int, gw: int, max_age: float | None = 3600) -> dict[str, Any]:
        return self.get(f"entry/{entry_id}/event/{gw}/picks/", f"entries/{entry_id}/picks_{gw:02d}", max_age)

    def league_classic(self, league_id: int, page: int = 1, max_age: float | None = 300) -> dict[str, Any]:
        return self.get(
            f"leagues-classic/{league_id}/standings/?page_standings={page}",
            f"leagues/{league_id}_p{page}",
            max_age,
        )

    def league_classic_all(self, league_id: int, max_pages: int = 20) -> tuple[dict[str, Any], list[dict]]:
        """Return (league meta, all standings rows) for a classic league."""
        rows: list[dict] = []
        meta: dict[str, Any] = {}
        for page in range(1, max_pages + 1):
            data = self.league_classic(league_id, page)
            meta = data.get("league", meta)
            standings = data.get("standings", {})
            rows.extend(standings.get("results", []))
            if not standings.get("has_next"):
                break
        return meta, rows
