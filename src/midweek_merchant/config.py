"""Project configuration: config.yaml merged with environment overrides."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]


class ForecastConfig(BaseModel):
    horizon: int = 8
    team_decay_per_day: float = 0.003
    xg_weight: float = 0.6
    market_weight_next: float = 0.9
    market_weight_decay: float = 0.6
    player_half_life_matches: float = 12
    prior_matches: float = 5
    n_sims: int = 3000


class OptimizerConfig(BaseModel):
    horizon: int = 6
    decay: float = 0.85
    bench_weights: list[float] = Field(default_factory=lambda: [0.03, 0.21, 0.06, 0.002])
    vice_weight: float = 0.05
    ft_values: dict[int, float] = Field(default_factory=lambda: {1: 1.5, 2: 2.0, 3: 1.6, 4: 1.3, 5: 1.1})
    itb_value: float = 0.08
    transfer_penalty: float = 0.05
    hit_cost: int = 4
    max_hits_per_gw: int = 2
    pool_size: int = 220
    mip_gap: float = 0.008
    time_limit: float = 45
    ft_after_chip: str = "freeze"
    chip_option_value: dict[str, float] = Field(
        default_factory=lambda: {"wildcard": 6.0, "freehit": 5.0, "bboost": 5.0, "3xc": 3.0}
    )


class OddsConfig(BaseModel):
    min_hours_between_calls: float = 12
    regions: str = "uk"
    markets: str = "h2h,totals"


class Settings(BaseModel):
    season: str = "2026-27"
    team_id: int | None = None
    league_id: int | None = None
    history_seasons: list[str] = Field(default_factory=lambda: ["2023-24", "2024-25", "2025-26"])
    forecast: ForecastConfig = Field(default_factory=ForecastConfig)
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    odds: OddsConfig = Field(default_factory=OddsConfig)
    odds_api_key: str | None = None
    data_dir: Path = ROOT / "data"

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def outputs_dir(self) -> Path:
        return self.data_dir / "outputs"

    def ensure_dirs(self) -> None:
        for d in (self.raw_dir, self.processed_dir, self.outputs_dir):
            d.mkdir(parents=True, exist_ok=True)


def _env_int(name: str) -> int | None:
    val = os.environ.get(name, "").strip()
    return int(val) if val.isdigit() else None


@lru_cache(maxsize=1)
def get_settings(path: str | None = None) -> Settings:
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    data = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    settings = Settings(**(data or {}))
    settings.team_id = _env_int("FPL_TEAM_ID") or settings.team_id
    settings.league_id = _env_int("FPL_LEAGUE_ID") or settings.league_id
    settings.odds_api_key = os.environ.get("ODDS_API_KEY") or settings.odds_api_key
    if os.environ.get("MM_DATA_DIR"):
        settings.data_dir = Path(os.environ["MM_DATA_DIR"])
    return settings
