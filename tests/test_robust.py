import numpy as np
import pandas as pd

from tremor import robust
from tremor.alpha import Rule


def _px(n=1500, start="2016-01-04", drift_after=(), seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    o, c = {}, {}
    for t in ("SPY", "BNO"):
        r = rng.normal(0, 0.01, n)
        if t == "BNO":
            for d in drift_after:
                i = idx.searchsorted(pd.Timestamp(d), side="right")
                r[i:i + 6] += 0.008
        close = 100 * np.cumprod(1 + r)
        c[t], o[t] = close, close / (1 + r)
    return pd.DataFrame(o, index=idx), pd.DataFrame(c, index=idx)


def _signals(n=60, start="2016-03-01", every=20):
    return [d.date() for d in pd.bdate_range(start, periods=n * every)[::every]][:n]


def test_a_real_planted_effect_passes_every_check():
    sig = _signals()
    o, c = _px(drift_after=sig)
    rep = robust.check_drift(Rule("s", "BNO", 5, 1), sig, o, c, draws=50)
    assert all(rep.passes.values()), rep.passes
    assert rep.placebo_share < 0.1 and rep.walk_forward_mean > 0


def test_noise_fails_the_random_date_check():
    sig = _signals()
    o, c = _px(seed=3)
    rep = robust.check_drift(Rule("s", "BNO", 5, 1), sig, o, c, draws=50)
    assert not rep.passes["beats random dates (<10%)"]


def test_drop_best_removes_lucky_outliers():
    rets = np.array([-0.01] * 10 + [0.5, 0.4])
    assert np.mean(rets) > 0 and robust.drop_best(rets) < 0
