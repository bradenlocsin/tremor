from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from tremor.config import load_config
from tremor.event_study import study
from tremor.events import Event
from tremor.robustness import bh_qvalues, fdr_adjust, placebo

CFG = load_config()
ES = CFG.event_study


def test_bh_matches_scipy():
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    assert np.allclose(bh_qvalues(p), stats.false_discovery_control(p))
    assert bh_qvalues([]) == []


def prices(n_days=2500, seed=1, jumps=()):
    """SPY and an Asset with beta 0.5 plus noise; `jumps` add a CAR of +5% over days 0..4."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2012-01-02", periods=n_days)
    spy = rng.normal(0.0004, 0.01, n_days)
    asset = 0.5 * spy + rng.normal(0, 0.01, n_days)
    for d in jumps:
        t = idx.searchsorted(pd.Timestamp(d))
        asset[t:t + 5] += 0.01
    return pd.DataFrame({"SPY": 100 * np.cumprod(1 + spy), "BNO": 100 * np.cumprod(1 + asset)},
                        index=idx)


def events(days):
    return [Event(id=f"e{i}", title="t", event_type="shipping_attack", region="red_sea",
                  occurred_on=d, reported_at=d.isoformat(), actors=(), summary="",
                  source_url="", source_name="", license="commercial") for i, d in
            enumerate(days)]


DAYS = [date(2013, 3, 4) + pd.Timedelta(days=150 * i) for i in range(12)]


def test_fdr_demotes_a_lone_borderline_result():
    r = study(prices(), events(DAYS), "BNO", "SPY", ES)
    h = r.headlines[5]
    fake = {a: replace(r, headlines={5: replace(h, p_value=p, significant=True),
                                     20: replace(r.headlines[20], p_value=0.9)})
            for a, p in (("BNO", 0.04), ("GLD", 0.5), ("ITA", 0.6), ("UUP", 0.7), ("BDRY", 0.8))}
    out = fdr_adjust(fake, ES)
    assert out["BNO"].headlines[5].q_value == pytest.approx(0.4)  # 0.04 * 10 tests / rank 1
    assert not out["BNO"].headlines[5].significant


def test_placebo_rejects_at_about_alpha_on_noise():
    px = prices()
    r = study(px, events(DAYS), "BNO", "SPY", ES)
    res = placebo(px, r, DAYS, "BNO", "SPY", ES, day=5, draws=400)
    assert 0.0 <= res.rejection_rate <= 0.12  # chance false-alarm rate near α = 0.05
    assert res.empirical_p > 0.05            # no real effect → real CAR looks ordinary


def test_placebo_detects_a_real_effect():
    px = prices(jumps=DAYS)
    r = study(px, events(DAYS), "BNO", "SPY", ES)
    res = placebo(px, r, DAYS, "BNO", "SPY", ES, day=5, draws=400)
    assert res.real_mean_car > 0.03 and res.empirical_p < 0.01
