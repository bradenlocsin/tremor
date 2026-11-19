"""Guards against finding effects that aren't there (ADR-0028).

* Multiple testing: one Analysis runs a test per Asset and headline day (10 tests for 5 Assets ×
  2 days). fdr_adjust() applies the Benjamini–Hochberg correction across them, so a
  Recommendation needs q < α rather than one lucky p < α.
* Placebo test: placebo() reruns the identical event study on random pseudo-event dates far from
  any real Event. It reports how often pure chance produces a "significant" CAR, and an
  empirical p-value for the real mean CAR (Monte Carlo randomization inference).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
from scipy import stats

from tremor.config import EventStudyConfig
from tremor.event_study import StudyResult, daily_returns, event_car

# Headline days a Recommendation can rest on; the multiple-testing family is these × Assets.
DECISION_DAYS = (5, 20)

# ---------------------------------------------------------------- Benjamini–Hochberg


def bh_qvalues(pvals: list[float]) -> list[float]:
    """Benjamini–Hochberg adjusted p-values (q-values), same order as the input."""
    m = len(pvals)
    if m == 0:
        return []
    order = np.argsort(pvals)
    ranked = np.asarray(pvals, dtype=float)[order] * m / np.arange(1, m + 1)
    q_sorted = np.minimum.accumulate(ranked[::-1])[::-1].clip(max=1.0)
    q = np.empty(m)
    q[order] = q_sorted
    return q.tolist()


def fdr_adjust(results: dict[str, StudyResult], cfg: EventStudyConfig) -> dict[str, StudyResult]:
    """Re-decide `significant` on every headline using BH q-values across the whole Analysis.

    Only tests that could support a Recommendation (enough Comparables, finite p) enter the
    family; the raw p-value is kept for display alongside the q-value.
    """
    family = [(asset, day, h.p_value) for asset, r in results.items() if not r.insufficient
              for day, h in r.headlines.items()
              if day in DECISION_DAYS and np.isfinite(h.p_value)]
    qs = dict(zip([(a, d) for a, d, _ in family], bh_qvalues([p for _, _, p in family])))
    out = {}
    for asset, r in results.items():
        heads = {}
        for day, h in r.headlines.items():
            q = qs.get((asset, day))
            sig = q is not None and r.n >= cfg.min_comparables and q < cfg.significance_level
            heads[day] = replace(h, q_value=q, significant=sig)
        out[asset] = replace(r, headlines=heads)
    return out


# ---------------------------------------------------------------- placebo test


@dataclass(frozen=True)
class PlaceboResult:
    asset: str
    day: int
    n_events: int
    draws: int
    real_mean_car: float
    real_p: float
    rejection_rate: float  # share of placebo draws with p < α: the false-alarm rate by chance
    empirical_p: float     # share of placebo |mean CAR| at least as large as the real one
    placebo_means: np.ndarray


def _pseudo_cars(returns: pd.DataFrame, asset: str, benchmark: str, cfg: EventStudyConfig,
                 day: int, blocked: set[int]) -> np.ndarray:
    """CAR at `day` for every eligible trading day used as a pseudo day 0."""
    out = []
    for t0, ts in enumerate(returns.index):
        if t0 in blocked:
            continue
        r = event_car(returns, SimpleNamespace(id=f"placebo-{t0}", occurred_on=ts.date()),
                      asset, benchmark, cfg)
        if not isinstance(r, str) and r.complete:
            out.append(float(r.car.loc[day]))
    return np.asarray(out)


def placebo(prices: pd.DataFrame, real: StudyResult, real_days: list, asset: str,
            benchmark: str, cfg: EventStudyConfig, day: int, draws: int = 1000,
            seed: int = 0) -> PlaceboResult | None:
    """Monte Carlo placebo for one Asset and headline day.

    Pseudo day-0s exclude any trading day whose window or estimation gap overlaps a real Event
    (±(window length + gap) trading days), so placebo windows contain no real shocks.
    """
    if real.n < 2 or day not in real.headlines:
        return None
    returns = daily_returns(prices, benchmark)
    idx = returns.index
    span = (cfg.window_end - cfg.window_start) + cfg.estimation_gap_days
    blocked: set[int] = set()
    for d in real_days:
        t = int(idx.searchsorted(pd.Timestamp(d)))
        blocked.update(range(t - span, t + span + 1))
    pool = _pseudo_cars(returns, asset, benchmark, cfg, day, blocked)
    if len(pool) < real.n * 5:
        return None
    rng = np.random.default_rng(seed)
    means, rejections = np.empty(draws), 0
    for i in range(draws):
        s = rng.choice(pool, size=real.n, replace=False)
        means[i] = s.mean()
        p = 2 * stats.t.sf(abs(s.mean() / (s.std(ddof=1) / np.sqrt(real.n))), df=real.n - 1)
        rejections += p < cfg.significance_level
    h = real.headlines[day]
    emp = (1 + np.sum(np.abs(means) >= abs(h.mean_car))) / (1 + draws)
    return PlaceboResult(asset, day, real.n, draws, h.mean_car, h.p_value,
                         rejections / draws, float(emp), means)
