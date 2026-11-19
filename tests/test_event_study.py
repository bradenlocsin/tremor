"""Event-study engine tests on synthetic prices where the right answer is known."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tremor.config import load_config
from tremor.event_study import daily_returns, event_car, select_comparables, study
from tremor.events import Event

CFG = load_config().event_study
ALPHA, BETA, JUMP = 0.0002, 1.5, 0.05


def make_prices(event_days: list[pd.Timestamp], noise: float = 0.0005, seed: int = 0):
    """SPY random walk; ASSET = alpha + beta*SPY + noise, plus a +5% abnormal jump on each day 0."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2015-01-01", "2024-12-31")
    mkt = rng.normal(0.0003, 0.01, len(days))
    asset = ALPHA + BETA * mkt + rng.normal(0, noise, len(days))
    for d in event_days:
        asset[days.get_loc(d)] += JUMP
    px = pd.DataFrame(
        {"SPY": 100 * np.cumprod(1 + mkt), "ASSET": 100 * np.cumprod(1 + asset)}, index=days
    )
    return px


def ev(i: int, d: pd.Timestamp, etype="shipping_attack", region="red_sea") -> Event:
    return Event(id=f"e{i}", title="t", event_type=etype, region=region, occurred_on=d.date())


EVENT_DAYS = [pd.Timestamp(f"{y}-0{m}-15") for y in range(2016, 2024) for m in (3, 9)]
EVENT_DAYS = [d + pd.offsets.BDay(0) for d in EVENT_DAYS]


def test_market_model_recovers_alpha_beta_and_the_jump():
    px = make_prices(EVENT_DAYS)
    r = event_car(daily_returns(px, "SPY"), ev(0, EVENT_DAYS[0]), "ASSET", "SPY", CFG)
    assert not isinstance(r, str)
    assert r.beta == pytest.approx(BETA, abs=0.05)
    assert r.alpha == pytest.approx(ALPHA, abs=0.0003)
    assert r.complete
    assert r.car[-1] == pytest.approx(0, abs=0.003)  # nothing before day 0
    assert r.car[0] == pytest.approx(JUMP, abs=0.005)
    assert r.car[20] == pytest.approx(JUMP, abs=0.01)  # no drift afterwards


def test_study_finds_a_significant_effect_with_enough_events():
    px = make_prices(EVENT_DAYS)
    events = [ev(i, d) for i, d in enumerate(EVENT_DAYS)]
    res = study(px, events, "ASSET", "SPY", CFG)
    assert res.n == len(EVENT_DAYS) and not res.insufficient
    assert res.headlines[1].mean_car == pytest.approx(JUMP, abs=0.005)
    assert res.headlines[5].significant
    # Events are ~126 trading days apart, so each estimation window catches the previous jump
    # and nudges alpha slightly; allow for that tiny bias against a very tight band.
    assert res.band_low[5] - 0.002 < JUMP < res.band_high[5] + 0.002


def test_no_effect_is_not_significant():
    px = make_prices([], noise=0.01, seed=3)  # no jumps at all
    events = [ev(i, d) for i, d in enumerate(EVENT_DAYS)]
    res = study(px, events, "ASSET", "SPY", CFG)
    assert not res.headlines[20].significant


def test_too_few_events_is_flagged_insufficient_and_never_significant():
    px = make_prices(EVENT_DAYS)
    events = [ev(i, d) for i, d in enumerate(EVENT_DAYS[:5])]
    res = study(px, events, "ASSET", "SPY", CFG)
    assert res.n == 5 and res.insufficient
    assert not any(h.significant for h in res.headlines.values())


def test_asset_without_history_is_skipped_with_a_reason():
    px = make_prices(EVENT_DAYS)
    px.loc[: "2018-03-21", "ASSET"] = np.nan  # like BDRY, which starts in 2018
    events = [ev(i, d) for i, d in enumerate(EVENT_DAYS)]
    res = study(px, events, "ASSET", "SPY", CFG)
    assert res.n < len(EVENT_DAYS)
    assert any("did not trade" in why for why in res.skipped.values())


def test_unfinished_window_is_excluded_from_the_average():
    px = make_prices(EVENT_DAYS)
    late = ev(99, pd.Timestamp("2024-12-24"))
    res = study(px, [late], "ASSET", "SPY", CFG)
    assert res.n == 0 and res.skipped["e99"] == "event window not finished yet"


def test_broadening_to_event_type_only():
    px = make_prices(EVENT_DAYS)
    red = [ev(i, d, region="red_sea") for i, d in enumerate(EVENT_DAYS[:3])]
    other = [ev(i + 50, d, region="hormuz") for i, d in enumerate(EVENT_DAYS[3:])]
    target = ev(999, pd.Timestamp("2024-06-03"))
    same_region, same_type = select_comparables(target, red + other)
    assert len(same_region) == 3
    res = study(px, same_region, "ASSET", "SPY", CFG, broader=same_type)
    assert res.broadened and res.n == len(EVENT_DAYS)


def test_comparables_exclude_later_events():
    target = ev(1, pd.Timestamp("2020-01-02"))
    pool = [ev(2, pd.Timestamp("2019-05-01")), ev(3, pd.Timestamp("2021-05-03"))]
    same_region, _ = select_comparables(target, pool)
    assert [e.id for e in same_region] == ["e2"]
    assert date(2019, 5, 1) == same_region[0].occurred_on
