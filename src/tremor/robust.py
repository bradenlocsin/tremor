"""Robustness checks for a rule that cleared the discovery bar (ADR-0032 follow-up).

Each check asks whether a winning rule is real or fragile. All of them use discovery data only;
the holdout stays locked. A rule is given as `trade_fn(start, end) -> trades DataFrame` so the
same checks apply to drift and fade rules alike.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from tremor.alpha import COST_BP, DISCOVERY_START, HOLDOUT_START, Rule, summarize, trades

TradeFn = Callable[[date, date], pd.DataFrame]


@dataclass(frozen=True)
class Report:
    rule: str
    base_mean: float
    neighbors: dict[str, float | None]   # nearby settings -> mean after costs
    double_cost_mean: float
    without_best2_mean: float
    by_year: dict[int, tuple[int, float]]  # year -> (trades, mean)
    placebo_share: float | None           # share of random-date runs that did as well or better
    walk_forward_mean: float | None       # mean of out-of-sample years, direction re-chosen yearly
    passes: dict[str, bool]


def drop_best(rets: np.ndarray, k: int = 2) -> float:
    return float(np.mean(np.sort(rets)[:-k])) if len(rets) > k else float("nan")


def by_year(t: pd.DataFrame) -> dict[int, tuple[int, float]]:
    if t.empty:
        return {}
    g = t.groupby(pd.to_datetime(t["entry"]).dt.year)["ret"]
    return {int(y): (int(n), float(m)) for y, n, m in zip(g.mean().index, g.size(), g.mean())}


def placebo(rule: Rule, n_signals: int, opens, closes, draws: int = 200, seed: int = 0,
            real_mean: float = 0.0) -> float | None:
    """Run the same rule on `draws` sets of random trading days (same count, discovery period).
    Returns the share that matched or beat the real mean: low means the real dates matter."""
    cal = closes[rule.asset].dropna().index
    cal = cal[(cal.date >= DISCOVERY_START) & (cal.date < HOLDOUT_START)]
    if len(cal) < n_signals or n_signals == 0:
        return None
    rng = np.random.default_rng(seed)
    beat = 0
    for _ in range(draws):
        days = [cal[i].date() for i in rng.choice(len(cal), n_signals, replace=False)]
        t = trades(days, opens, closes, rule)
        if len(t) and t["ret"].mean() >= real_mean:
            beat += 1
    return beat / draws


def walk_forward(rule: Rule, known_on, opens, closes, first_test_year: int = 2018) -> float | None:
    """Each year from `first_test_year`, choose long or short from the sign of the rule's mean on
    all earlier discovery years, then trade that year. Returns the mean of those out-of-sample
    trades: what you'd have earned using the rule the way it would really be used."""
    out = []
    for y in range(first_test_year, HOLDOUT_START.year + 1):
        train = trades(known_on, opens, closes, Rule(rule.signal, rule.asset, rule.hold, 1,
                                                     rule.hedge), end=date(y, 1, 1))
        if len(train) < 5:
            continue
        direction = 1 if train["ret"].mean() > 0 else -1
        test = trades(known_on, opens, closes,
                      Rule(rule.signal, rule.asset, rule.hold, direction, rule.hedge),
                      start=date(y, 1, 1), end=min(date(y + 1, 1, 1), HOLDOUT_START))
        out.extend(test["ret"].tolist())
    return float(np.mean(out)) if out else None


HOLDS = (1, 2, 5, 10, 20)


def check_drift(rule: Rule, known_on, opens, closes, draws: int = 200) -> Report:
    base = trades(known_on, opens, closes, rule)
    rets = base["ret"].to_numpy()
    s = summarize(rets)
    i = HOLDS.index(rule.hold) if rule.hold in HOLDS else None
    neighbors = {}
    for h in ([HOLDS[i - 1]] if i else []) + ([HOLDS[i + 1]] if i is not None
                                               and i + 1 < len(HOLDS) else []):
        t = trades(known_on, opens, closes, Rule(rule.signal, rule.asset, h, rule.direction,
                                                 rule.hedge))
        neighbors[f"{h}d"] = float(t["ret"].mean()) if len(t) else None
    other_hedge = trades(known_on, opens, closes, Rule(rule.signal, rule.asset, rule.hold,
                                                       rule.direction, not rule.hedge))
    neighbors["hedge flipped"] = float(other_hedge["ret"].mean()) if len(other_hedge) else None
    one_way = COST_BP[rule.asset] / 1e4 + (COST_BP["SPY"] / 1e4 if rule.hedge else 0)
    double = float(np.mean(rets - 2 * one_way)) if len(rets) else float("nan")
    best2 = drop_best(rets)
    years = by_year(base)
    plac = placebo(rule, len(set(known_on)), opens, closes, draws, real_mean=s["mean"] or 0)
    wf = walk_forward(rule, known_on, opens, closes)
    positive_years = sum(m > 0 for n, m in years.values() if n >= 2)
    counted_years = sum(1 for n, _ in years.values() if n >= 2)
    passes = {
        "neighbors same sign": all(v is not None and v > 0 for v in neighbors.values()),
        "survives double costs": double > 0,
        "not just the 2 best trades": best2 > 0,
        "positive in most years": counted_years > 0 and positive_years / counted_years > 0.5,
        "beats random dates (<10%)": plac is not None and plac < 0.10,
        "walk-forward positive": wf is not None and wf > 0,
    }
    return Report(rule.name(), s["mean"], neighbors, double, best2, years, plac, wf, passes)
