"""Load TREMOR's configuration from config/tremor.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "tremor.toml"


@dataclass(frozen=True)
class AssetConfig:
    ticker: str
    name: str
    category: str


@dataclass(frozen=True)
class EventStudyConfig:
    estimation_window_days: int
    estimation_gap_days: int
    window_start: int
    window_end: int
    headline_days: tuple[int, ...]
    significance_level: float
    min_comparables: int
    episode_gap_trading_days: int


@dataclass(frozen=True)
class Config:
    storage_path: Path
    benchmark: str
    assets: tuple[AssetConfig, ...]
    event_study: EventStudyConfig
    refinement_model: str
    rationale_model: str
    daily_llm_usd: float
    backfill_llm_usd: float
    recommendations_enabled: bool = True

    @property
    def tickers(self) -> list[str]:
        """Every ticker TREMOR needs prices for: the benchmark plus the Asset universe."""
        return [self.benchmark, *(a.ticker for a in self.assets)]


def load_config(path: Path | str = DEFAULT_CONFIG) -> Config:
    raw = tomllib.loads(Path(path).read_text())
    es = raw["event_study"]
    storage = Path(raw["storage"]["path"])
    if not storage.is_absolute():
        storage = REPO_ROOT / storage
    return Config(
        storage_path=storage,
        benchmark=raw["benchmark"]["ticker"],
        assets=tuple(AssetConfig(**a) for a in raw["assets"]),
        event_study=EventStudyConfig(
            estimation_window_days=es["estimation_window_days"],
            estimation_gap_days=es["estimation_gap_days"],
            window_start=es["window_start"],
            window_end=es["window_end"],
            headline_days=tuple(es["headline_days"]),
            significance_level=es["significance_level"],
            min_comparables=es["min_comparables"],
            episode_gap_trading_days=es["episode_gap_trading_days"],
        ),
        refinement_model=raw["models"]["refinement"],
        rationale_model=raw["models"]["rationale"],
        daily_llm_usd=raw["budget"]["daily_llm_usd"],
        backfill_llm_usd=raw["budget"]["backfill_llm_usd"],
        recommendations_enabled=raw.get("recommendations", {}).get("enabled", True),
    )
