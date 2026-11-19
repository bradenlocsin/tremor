from dataclasses import replace

import pandas as pd

from tremor.analysis import analyze_event
from tremor.config import load_config
from tremor.events import Event
from tremor.recommend import (
    FakeExplainer, Rationale, apply_rationale, compute_confidence, decide, recommend,
    save_recommendations,
)
from tremor.storage import connect

from tests.test_event_study import EVENT_DAYS, make_prices

CFG = load_config()


def setup(jump_days=EVENT_DAYS, noise=0.0005):
    px = make_prices(jump_days, noise=noise).rename(columns={"ASSET": "BNO"})
    for a in CFG.assets:
        if a.ticker not in px:
            px[a.ticker] = px["SPY"]  # no abnormal moves at all
    evs = [Event(f"e{i}", f"attack {i}", "shipping_attack", "red_sea", d.date())
           for i, d in enumerate(EVENT_DAYS)]
    target = Event("now", "new attack", "shipping_attack", "red_sea",
                   (EVENT_DAYS[-1] + pd.offsets.BDay(60)).date())
    return px, evs, target


def test_significant_positive_car_gives_overweight_with_citation():
    px, evs, target = setup()
    a = analyze_event(target, evs + [target], px, CFG)
    recs = {r.asset: r for r in recommend(a, {e.id: e for e in evs}, FakeExplainer())}
    bno = recs["BNO"]
    assert bno.stance == "Overweight" and bno.horizon_days in (5, 20)
    assert bno.mean_car > 0.04 and bno.n == len(EVENT_DAYS)
    assert bno.confidence == bno.confidence_computed == "High"
    assert set(bno.comparables) == {e.id for e in evs}
    assert bno.rationale.startswith("(template rationale) Overweight BNO")
    # assets with no abnormal moves get no Recommendation
    assert not recs["GLD"].exists and recs["GLD"].no_rec_reason


def test_insufficient_n_never_recommends():
    px, evs, target = setup()
    a = analyze_event(target, evs[:5] + [target], px, CFG)
    rec = decide(target, "BNO", a.results["BNO"], {})
    assert not rec.exists and "minimum 8" in rec.no_rec_reason


def test_confidence_rules():
    assert compute_confidence(20, 4.0, 0.05, False, False) == "High"
    assert compute_confidence(20, 4.0, 0.05, False, True) == "Med"  # mostly lower Fidelity
    assert compute_confidence(8, 2.4, 0.01, False, False) == "Low"
    assert compute_confidence(20, 4.0, 0.05, True, False) == "Med"  # broadened


def test_llm_may_only_downgrade():
    px, evs, target = setup()
    a = analyze_event(target, evs + [target], px, CFG)
    rec = decide(target, "BNO", a.results["BNO"], {})
    down = apply_rationale(rec, Rationale(rationale="x", downgrade_to="Low",
                                          downgrade_reason="inventories high"), "m")
    assert down.confidence == "Low" and down.downgrade_reason == "inventories high"
    assert down.stance == rec.stance
    low = replace(rec, confidence_computed="Low", confidence="Low")
    up = apply_rationale(low, Rationale(rationale="x", downgrade_to="Med"), "m")
    assert up.confidence == "Low" and up.downgrade_reason is None  # an "upgrade" is ignored


def test_recommendations_persist(tmp_path):
    px, evs, target = setup()
    a = analyze_event(target, evs + [target], px, CFG)
    recs = recommend(a, {e.id: e for e in evs}, FakeExplainer())
    conn = connect(tmp_path / "t.sqlite")
    save_recommendations(conn, recs)
    save_recommendations(conn, recs)
    assert conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0] == len(CFG.assets)
