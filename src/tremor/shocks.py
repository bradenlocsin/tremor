"""The pre-registered shock-feature tests (ADR-0031). Run once, on the complete history.

Every choice below is fixed by ADR-0031 and must not be tuned after seeing results: the
features and the 0.7 / 0.3 reading of Jev's answers, the hypotheses, the Assets and days, the
5-trading-day spacing of shocks, Welch's t-test, and Benjamini–Hochberg across all 11 tests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from tremor.config import Config
from tremor.event_study import daily_returns, event_car
from tremor.events import Event
from tremor.jev import flag
from tremor.robustness import bh_qvalues

SPACING = 5  # trading days between shocks in one series, so +5-day windows don't overlap
FIRST_SLICE = ("shipping_attack", "military_strike", "chokepoint_disruption")


@dataclass(frozen=True)
class Hypothesis:
    id: str
    feature: str
    types: tuple[str, ...]
    assets: tuple[str, ...]
    days: tuple[int, ...]
    absolute: bool  # compare |CAR| (size of the move) rather than signed CAR


# The family of 11 tests, exactly as pre-registered.
HYPOTHESES = (
    Hypothesis("H1", "vessel_damaged", ("shipping_attack",), ("BNO", "BDRY"), (5, 20), False),
    Hypothesis("H2", "energy_target", ("shipping_attack",), ("BNO",), (5, 20), False),
    Hypothesis("H3", "escalation", FIRST_SLICE, ("BNO", "GLD", "ITA", "BDRY", "UUP"), (5,), True),
)


@dataclass(frozen=True)
class TestResult:
    hypothesis: str
    feature: str
    asset: str
    day: int
    n_yes: int
    n_no: int
    mean_yes: float
    mean_no: float
    p_value: float
    q_value: float
    significant: bool
    note: str = ""


def thin(events: list[Event], calendar: pd.DatetimeIndex, spacing: int = SPACING) -> list[Event]:
    """Shocks: walk Events by date; keep one when it is >= `spacing` trading days after the
    previously kept one."""
    out, last = [], None
    for e in sorted(events, key=lambda e: (e.occurred_on, e.id)):
        t = int(calendar.searchsorted(pd.Timestamp(e.occurred_on)))
        if last is None or t - last >= spacing:
            out.append(e)
            last = t
    return out


def _cars(returns, events, asset, cfg, day) -> list[float]:
    out = []
    for e in events:
        r = event_car(returns, e, asset, cfg.benchmark, cfg.event_study)
        if not isinstance(r, str) and r.complete and day in r.car.index:
            out.append(float(r.car.loc[day]))
    return out


def run(events: list[Event], features: dict[str, dict[str, float]], prices: pd.DataFrame,
        cfg: Config, region: str = "red_sea") -> list[TestResult]:
    returns = daily_returns(prices, cfg.benchmark)
    cal = returns.index
    rows = []
    for h in HYPOTHESES:
        pool = [e for e in events if e.region == region and e.event_type in h.types
                and e.source_url in features]
        yes = [e for e in pool if flag(features[e.source_url][h.feature]) is True]
        no = [e for e in pool if flag(features[e.source_url][h.feature]) is False]
        # Shocks are built within each group, and per Event type for H3 (ADR-0031).
        yes_s = [s for t in h.types for s in thin([e for e in yes if e.event_type == t], cal)]
        no_s = [s for t in h.types for s in thin([e for e in no if e.event_type == t], cal)]
        for asset in h.assets:
            for day in h.days:
                a = np.asarray(_cars(returns, yes_s, asset, cfg, day))
                b = np.asarray(_cars(returns, no_s, asset, cfg, day))
                if h.absolute:
                    a, b = np.abs(a), np.abs(b)
                if min(len(a), len(b)) < cfg.event_study.min_comparables:
                    # Too few shocks: kept in the family as p = 1 (conservative), never dropped.
                    p, note = 1.0, f"fewer than {cfg.event_study.min_comparables} shocks"
                else:
                    p, note = float(stats.ttest_ind(a, b, equal_var=False).pvalue), ""
                rows.append([h.id, h.feature, asset, day, len(a), len(b),
                             float(a.mean()) if len(a) else math.nan,
                             float(b.mean()) if len(b) else math.nan, p, note])
    qs = bh_qvalues([r[8] for r in rows])
    alpha = cfg.event_study.significance_level
    return [TestResult(*r[:9], q_value=q, significant=q < alpha and not r[9], note=r[9])
            for r, q in zip(rows, qs)]
