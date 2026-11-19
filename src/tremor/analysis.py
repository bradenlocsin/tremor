"""Analysis: event studies over Episode-start Comparables (ADR-0010, ADR-0011, ADR-0020)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from tremor.config import Config
from tremor.episodes import Episode, build_episodes, episode_of, episode_starts
from tremor.event_study import StudyResult, daily_returns, select_comparables, study
from tremor.events import Event
from tremor.robustness import fdr_adjust


@dataclass(frozen=True)
class Analysis:
    target: Event
    episode: Episode | None
    results: dict[str, StudyResult]  # per Asset ticker


def episodes_for(events: list[Event], prices: pd.DataFrame, cfg: Config) -> list[Episode]:
    calendar = daily_returns(prices, cfg.benchmark).index
    return build_episodes(events, calendar, cfg.event_study.episode_gap_trading_days)


def analyze_event(
    target: Event, events: list[Event], prices: pd.DataFrame, cfg: Config,
    episodes: list[Episode] | None = None,
) -> Analysis:
    """Event study for `target` using only Episode starts that happened before it.

    A target inside an ongoing Episode is analyzed as that Episode's first Event, because
    later Events in a burst get the Episode's Analysis rather than their own (ADR-0020).
    """
    episodes = episodes if episodes is not None else episodes_for(events, prices, cfg)
    ep = episode_of(target.id, episodes)
    anchor = ep.first if ep else target
    same_region, same_type = select_comparables(anchor, episode_starts(episodes))
    results = {
        a.ticker: study(prices, same_region, a.ticker, cfg.benchmark, cfg.event_study,
                        broader=same_type)
        for a in cfg.assets
    }
    # One Analysis tests every Asset × headline day; correct for that family (ADR-0028).
    return Analysis(target=target, episode=ep, results=fdr_adjust(results, cfg.event_study))


def analyze_group(
    event_type: str, region: str, events: list[Event], prices: pd.DataFrame, cfg: Config
) -> dict[str, StudyResult]:
    """Event study over every Episode start of one type in one Region (charts, reports)."""
    starts = [
        e for e in episode_starts(episodes_for(events, prices, cfg))
        if e.event_type == event_type
    ]
    same_region = [e for e in starts if e.region == region]
    return fdr_adjust({
        a.ticker: study(prices, same_region, a.ticker, cfg.benchmark, cfg.event_study,
                        broader=starts)
        for a in cfg.assets
    }, cfg.event_study)
