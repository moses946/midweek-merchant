"""Publish/sync the data bundle via the repository's ``data`` branch.

The scheduled GitHub Action writes ``outputs/``, the small ``processed/`` tables and
the point-in-time snapshot archive to an orphan ``data`` branch (force-pushed as a
single commit so the repository does not grow). The dashboard reads that bundle when
it has no local data, e.g. on Streamlit Community Cloud.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import httpx

from midweek_merchant.config import Settings

log = logging.getLogger(__name__)

REPO = "moses946/midweek-merchant"
REMOTE_BASE = f"https://raw.githubusercontent.com/{REPO}/data"
PROCESSED = [
    "players",
    "teams",
    "events",
    "fixtures",
    "player_matches",
    "team_matches",
    "fd_e1",
    "market_odds",
]


def build_bundle(settings: Settings, dest: Path) -> dict:
    """Copy publishable files into ``dest`` and write a manifest."""
    files: list[str] = []
    (dest / "outputs").mkdir(parents=True, exist_ok=True)
    (dest / "processed").mkdir(parents=True, exist_ok=True)
    for f in sorted(settings.outputs_dir.glob("*")):
        if f.is_file():
            shutil.copy2(f, dest / "outputs" / f.name)
            files.append(f"outputs/{f.name}")
    for name in PROCESSED:
        f = settings.processed_dir / f"{name}.parquet"
        if f.exists():
            shutil.copy2(f, dest / "processed" / f.name)
            files.append(f"processed/{f.name}")
    bs = settings.raw_dir / "fpl" / "bootstrap.json"
    if bs.exists():
        (dest / "raw" / "fpl").mkdir(parents=True, exist_ok=True)
        shutil.copy2(bs, dest / "raw" / "fpl" / "bootstrap.json")
        files.append("raw/fpl/bootstrap.json")
    snap_src = settings.raw_dir / "snapshots"
    if snap_src.exists():
        for f in sorted(snap_src.glob("*/players_*.parquet")):
            rel = f.relative_to(settings.raw_dir)
            (dest / "raw" / rel.parent).mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest / "raw" / rel)
    manifest = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "files": files}
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


def sync_from_remote(settings: Settings, base: str = REMOTE_BASE, timeout: float = 60) -> dict:
    """Download the published bundle into ``settings.data_dir``."""
    settings.ensure_dirs()
    with httpx.Client(timeout=timeout, follow_redirects=True) as http:
        resp = http.get(f"{base}/manifest.json")
        resp.raise_for_status()
        manifest = resp.json()
        for rel in manifest["files"]:
            target = settings.data_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            r = http.get(f"{base}/{rel}")
            r.raise_for_status()
            target.write_bytes(r.content)
    log.info("synced %d files from %s", len(manifest["files"]), base)
    return manifest
