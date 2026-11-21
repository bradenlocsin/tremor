import sqlite3
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tremor import alpha
from tremor.alpha import HoldoutError, Rule


def _px(n=600, start="2020-01-01", drift_after=None, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    out_o, out_c = {}, {}
    for t in ("SPY", "BNO"):
        r = rng.normal(0, 0.01, n)
        if t == "BNO" and drift_after is not None:
            for d in drift_after:
                i = idx.searchsorted(pd.Timestamp(d), side="right")
                r[i:i + 3] += 0.01  # +1% a day for 3 days after each signal
        c = 100 * np.cumprod(1 + r)
        out_c[t] = c
        out_o[t] = c / (1 + r)  # open = previous close, so the whole day's move is tradable
    return pd.DataFrame(out_o, index=idx), pd.DataFrame(out_c, index=idx)


def _signals(n=40, start="2020-02-03", every=12):
    idx = pd.bdate_range(start, periods=n * every)
    return [d.date() for d in idx[::every]][:n]


def test_enters_after_known_day_and_never_overlaps():
    sig = _signals()
    o, c = _px()
    t = alpha.trades(sig + [sig[0]], o, c, Rule("s", "BNO", 20, 1))
    assert (pd.to_datetime(t["entry"]) > pd.to_datetime(t["known_on"])).all()
    assert (pd.to_datetime(t["entry"]).iloc[1:].values
            > pd.to_datetime(t["exit"]).iloc[:-1].values).all()


def test_holdout_is_refused_unless_confirming():
    o, c = _px(start="2025-06-02")
    with pytest.raises(HoldoutError):
        alpha.trades([date(2025, 12, 1)], o, c, Rule("s", "BNO", 1, 1), end=date(2026, 6, 1))
    assert alpha.trades([date(2025, 12, 1)], o, c, Rule("s", "BNO", 1, 1)).empty


def test_finds_planted_drift_after_costs_and_not_noise():
    sig = _signals()
    o, c = _px(drift_after=sig)
    conn = sqlite3.connect(":memory:")
    real = alpha.evaluate(conn, sig, o, c, Rule("s", "BNO", 3, 1))
    assert real["mean"] > 0.02 and real["t"] > 5
    noise = alpha.evaluate(conn, sig, *_px(seed=1), Rule("s", "BNO", 3, 1))
    assert abs(noise["t"]) < 3
    assert [r["rule"] for r in alpha.promote(conn, [real, noise])] == [real["rule"]]


def test_more_trials_raise_the_bar():
    few = alpha.deflated_sharpe(0.3, 40, 0.0, 3.0, [0.3, 0.0])
    many = alpha.deflated_sharpe(0.3, 40, 0.0, 3.0, list(np.random.default_rng(0).normal(0, 0.15, 500)))
    assert many < few


def test_costs_are_charged_both_ways():
    o, c = _px()
    flat_o = o.copy(); flat_c = c.copy()
    flat_o["BNO"] = 100.0; flat_c["BNO"] = 100.0
    t = alpha.trades(_signals(5), flat_o, flat_c, Rule("s", "BNO", 1, 1))
    assert np.allclose(t["ret"], -2 * alpha.COST_BP["BNO"] / 1e4)


def test_fade_bets_against_the_spike_and_skips_small_moves():
    o, c = _px()
    idx = c.index
    occ, k = idx[100].date(), idx[101].date()
    c.loc[idx[100]:, "BNO"] *= 1.10          # +10% spike on the Event day ...
    o.loc[idx[101]:, "BNO"] *= 1.10
    c.loc[idx[103]:, "BNO"] /= 1.05          # ... that gives half back two days later
    o.loc[idx[104]:, "BNO"] /= 1.05
    t = alpha.fade_trades([(occ, k)], o, c, "BNO", 3, 0.05)
    assert len(t) == 1 and t["entry"].iloc[0] == idx[102].date() and t["ret"].iloc[0] > 0.03
    assert alpha.fade_trades([(occ, k)], o, c, "BNO", 3, 0.5).empty


def test_intensity_uses_only_what_was_known_the_day_before():
    o, _ = _px(n=600)
    cal = o.index
    burst = [d.date() for d in cal[400:410]]
    r = alpha.intensity_returns(burst, o, "BNO", window=20, base=250)
    held = r[r != 0].index
    assert held.min() > cal[400]  # first held open is after the first Event was known
