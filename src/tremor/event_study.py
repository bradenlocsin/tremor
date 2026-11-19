"""Event studies with market-model abnormal returns (ADR-0010, MacKinlay 1997).

For one Event and one Asset:
  * day 0 is the first trading day on or after the Event's date
  * a market model  R_asset = alpha + beta * R_benchmark  is fit by OLS over an estimation window
    that ends `estimation_gap_days` before the event window starts (so the Event can't leak in)
  * abnormal return AR_t = R_asset,t - (alpha + beta * R_benchmark,t)
  * CAR(tau) = sum of AR from window_start to tau

Across Comparables, the average CAR path gets a cross-sectional t-test and confidence band.
The cross-sectional test uses the spread of CARs across Events, so it stays valid when an
Event changes volatility (a known weakness of tests that rely on estimation-window variance).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from scipy import stats

from tremor.config import EventStudyConfig
from tremor.events import Event


@dataclass(frozen=True)
class EventCar:
    """One Event's abnormal-return path for one Asset."""

    event_id: str
    asset: str
    day0: date
    alpha: float
    beta: float
    resid_sd: float
    ar: pd.Series  # indexed by relative day
    complete: bool  # False when the event window runs past the latest price

    @property
    def car(self) -> pd.Series:
        return self.ar.cumsum()


@dataclass(frozen=True)
class Headline:
    day: int
    mean_car: float
    t_stat: float
    p_value: float
    significant: bool
    q_value: float | None = None  # Benjamini–Hochberg across the Analysis (ADR-0028)


@dataclass(frozen=True)
class StudyResult:
    """Average CAR across Comparables for one Asset."""

    asset: str
    n: int
    event_ids: tuple[str, ...]
    mean_car: pd.Series
    band_low: pd.Series
    band_high: pd.Series
    headlines: dict[int, Headline]
    broadened: bool = False
    insufficient: bool = False  # n below the minimum: shown, but no Recommendation may rely on it
    skipped: dict[str, str] = field(default_factory=dict)  # event_id -> reason


def daily_returns(prices: pd.DataFrame, benchmark: str) -> pd.DataFrame:
    """Simple daily returns on the benchmark's trading calendar."""
    px = prices[prices[benchmark].notna()]
    return px.pct_change(fill_method=None).iloc[1:]


def event_car(
    returns: pd.DataFrame,
    event: Event,
    asset: str,
    benchmark: str,
    cfg: EventStudyConfig,
) -> EventCar | str:
    """Abnormal returns for one Event and Asset, or a string saying why it was skipped."""
    idx = returns.index
    t0 = int(idx.searchsorted(pd.Timestamp(event.occurred_on)))
    if t0 >= len(idx):
        return "no trading days after the Event yet"
    est_end = t0 + cfg.window_start - cfg.estimation_gap_days  # exclusive
    est_start = est_end - cfg.estimation_window_days
    if est_start < 0:
        return "not enough price history before the Event"
    est = returns.iloc[est_start:est_end][[asset, benchmark]]
    if est[asset].isna().any():
        return f"{asset} did not trade for the whole estimation window"

    beta, alpha = np.polyfit(est[benchmark].to_numpy(), est[asset].to_numpy(), 1)
    resid = est[asset] - (alpha + beta * est[benchmark])
    resid_sd = float(resid.std(ddof=2))

    win_start = t0 + cfg.window_start
    win_end = min(t0 + cfg.window_end + 1, len(idx))
    win = returns.iloc[win_start:win_end][[asset, benchmark]]
    if win[asset].isna().any():
        return f"{asset} has missing prices inside the event window"
    ar = win[asset] - (alpha + beta * win[benchmark])
    ar.index = range(cfg.window_start, cfg.window_start + len(ar))
    return EventCar(
        event_id=event.id,
        asset=asset,
        day0=idx[t0].date(),
        alpha=float(alpha),
        beta=float(beta),
        resid_sd=resid_sd,
        ar=ar,
        complete=len(ar) == cfg.window_end - cfg.window_start + 1,
    )


def aggregate(
    cars: list[EventCar], asset: str, cfg: EventStudyConfig, skipped: dict[str, str],
    broadened: bool = False,
) -> StudyResult:
    """Average complete CAR paths with a cross-sectional t-test and confidence band."""
    complete = [c for c in cars if c.complete]
    for c in cars:
        if not c.complete:
            skipped[c.event_id] = "event window not finished yet"
    days = list(range(cfg.window_start, cfg.window_end + 1))
    n = len(complete)
    if n == 0:
        empty = pd.Series(np.nan, index=days)
        return StudyResult(asset, 0, (), empty, empty, empty, {}, broadened, True, skipped)

    mat = pd.DataFrame({c.event_id: c.car for c in complete}).reindex(days)
    mean = mat.mean(axis=1)
    if n > 1:
        se = mat.std(axis=1, ddof=1) / np.sqrt(n)
        crit = stats.t.ppf(1 - cfg.significance_level / 2, df=n - 1)
        low, high = mean - crit * se, mean + crit * se
    else:
        se = pd.Series(np.nan, index=days)
        low = high = pd.Series(np.nan, index=days)

    headlines = {}
    for d in cfg.headline_days:
        if n > 1 and se[d] > 0:
            t = float(mean[d] / se[d])
            p = float(2 * stats.t.sf(abs(t), df=n - 1))
        else:
            t, p = float("nan"), float("nan")
        headlines[d] = Headline(
            d, float(mean[d]), t, p,
            significant=bool(n >= cfg.min_comparables and p < cfg.significance_level),
        )
    return StudyResult(
        asset=asset,
        n=n,
        event_ids=tuple(c.event_id for c in complete),
        mean_car=mean,
        band_low=low,
        band_high=high,
        headlines=headlines,
        broadened=broadened,
        insufficient=n < cfg.min_comparables,
        skipped=skipped,
    )


def select_comparables(target: Event, pool: list[Event]) -> tuple[list[Event], list[Event]]:
    """Comparables for `target` (ADR-0011): Events strictly before it with the same Event type.

    Returns (same type + Region, same type any Region). The caller broadens to the second list
    only when the first yields fewer valid results than the minimum.
    """
    earlier = [e for e in pool if e.occurred_on < target.occurred_on and e.id != target.id]
    same_type = [e for e in earlier if e.event_type == target.event_type]
    same_region = [e for e in same_type if e.region == target.region]
    return same_region, same_type


def study(
    prices: pd.DataFrame,
    comparables: list[Event],
    asset: str,
    benchmark: str,
    cfg: EventStudyConfig,
    broader: list[Event] | None = None,
) -> StudyResult:
    """Event study over `comparables`; falls back to `broader` if too few are usable."""
    returns = daily_returns(prices, benchmark)

    def run(events: list[Event], broadened: bool) -> StudyResult:
        cars, skipped = [], {}
        for e in events:
            r = event_car(returns, e, asset, benchmark, cfg)
            if isinstance(r, str):
                skipped[e.id] = r
            else:
                cars.append(r)
        return aggregate(cars, asset, cfg, skipped, broadened)

    result = run(comparables, broadened=False)
    if result.insufficient and broader and len(broader) > len(comparables):
        wider = run(broader, broadened=True)
        if wider.n > result.n:
            return wider
    return result
