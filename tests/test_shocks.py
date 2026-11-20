"""Pre-registered shock tests (ADR-0031), checked on synthetic data only."""

from datetime import date

import numpy as np
import pandas as pd

from tremor import shocks
from tremor.config import load_config
from tremor.events import Event

CFG = load_config()
ASSETS = ("BNO", "GLD", "ITA", "BDRY", "UUP")


def prices(effect_days=(), n_days=3000, seed=4):
    """SPY plus five Assets with beta 0.5 and noise; `effect_days` add +1%/day to BNO for 5 days."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=n_days)
    spy = rng.normal(0.0004, 0.01, n_days)
    cols = {"SPY": spy}
    for a in ASSETS:
        cols[a] = 0.5 * spy + rng.normal(0, 0.01, n_days)
    for d in effect_days:
        t = idx.searchsorted(pd.Timestamp(d))
        cols["BNO"][t:t + 5] += 0.01
    return pd.DataFrame({k: 100 * np.cumprod(1 + v) for k, v in cols.items()}, index=idx)


def event(i, d, etype="shipping_attack"):
    return Event(id=f"e{i}", title="t", event_type=etype, region="red_sea", occurred_on=d,
                 reported_at=d.isoformat(), actors=(), summary="", source_url=f"u{i}",
                 source_name="", license="commercial")


def fixture(n=60, planted=True):
    days = [(pd.Timestamp("2013-06-03") + pd.offsets.BDay(30 * i)).date() for i in range(n)]
    evs = [event(i, d) for i, d in enumerate(days)]
    damaged = {e.id for e in evs[::2]}  # every other attack damages a ship
    feats = {e.source_url: {"vessel_damaged": 0.9 if e.id in damaged else 0.1,
                            "energy_target": 0.5,  # unsure: left out of H2
                            "fatalities": 0.1, "escalation": 0.1} for e in evs}
    effect = [e.occurred_on for e in evs if e.id in damaged] if planted else []
    return evs, feats, prices(effect)


def by_key(res):
    return {(r.hypothesis, r.asset, r.day): r for r in res}


def test_family_is_the_preregistered_eleven():
    evs, feats, px = fixture(planted=False)
    res = shocks.run(evs, feats, px, CFG)
    assert len(res) == 11
    assert sorted({r.hypothesis for r in res}) == ["H1", "H2", "H3"]


def test_finds_a_planted_effect_and_only_that():
    evs, feats, px = fixture()
    res = by_key(shocks.run(evs, feats, px, CFG))
    h1 = res[("H1", "BNO", 5)]
    assert h1.n_yes == h1.n_no == 30 and h1.mean_yes - h1.mean_no > 0.03
    assert h1.significant and h1.q_value < 0.01
    assert not res[("H1", "BDRY", 5)].significant  # no effect planted on shipping


def test_quiet_on_noise_and_conservative_when_groups_are_small():
    evs, feats, px = fixture(planted=False)
    res = by_key(shocks.run(evs, feats, px, CFG))
    assert not any(r.significant for r in res.values())
    h2 = res[("H2", "BNO", 5)]  # every energy answer is unsure -> empty groups
    assert h2.p_value == 1.0 and "fewer than" in h2.note and not h2.significant


def test_thin_keeps_shocks_at_least_five_trading_days_apart():
    cal = pd.bdate_range("2024-01-01", periods=60)
    days = [date(2024, 1, d) for d in (2, 3, 5, 9, 10, 16)]
    kept = shocks.thin([event(i, d) for i, d in enumerate(days)], cal)
    assert [e.occurred_on.day for e in kept] == [2, 9, 16]
