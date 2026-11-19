import pandas as pd

from tremor.backtest import prices_before, run_backtest, save_backtest, summarize
from tremor.config import load_config
from tremor.events import Event
from tremor.storage import connect

from tests.test_event_study import EVENT_DAYS, make_prices

CFG = load_config()


def market(jump_days):
    px = make_prices(jump_days).rename(columns={"ASSET": "BNO"})
    for a in CFG.assets:
        if a.ticker not in px:
            px[a.ticker] = px["SPY"]
    return px


def events():
    return [Event(f"e{i}", f"attack {i}", "shipping_attack", "red_sea", d.date())
            for i, d in enumerate(EVENT_DAYS)]


def test_prices_before_cuts_at_day0():
    px = market(EVENT_DAYS)
    ev = events()[3]
    cut = prices_before(px, ev, "SPY")
    assert cut.index.max() < pd.Timestamp(ev.occurred_on)


def test_backtest_makes_no_call_until_enough_history_then_scores_hits():
    px = market(EVENT_DAYS)
    calls = run_backtest(events(), px, CFG)
    assert calls, "expected calls once 8 earlier Episodes exist"
    # the first call can only come at the 9th Event (8 earlier, finished Comparables)
    first = min(c.occurred_on for c in calls)
    assert first >= EVENT_DAYS[8].date().isoformat()
    assert all(c.asset == "BNO" for c in calls)  # other Assets have no abnormal moves
    assert all(c.hit and c.stance == "Overweight" for c in calls)  # the jump repeats every time
    summary = summarize(calls).set_index("group")
    assert summary.loc["all", "hit_rate"] == 1.0
    assert summary.loc["all", "avg_signed_car"] > 0.04


def test_no_look_ahead_when_the_pattern_flips():
    """If the effect reverses, early calls must be wrong: they can't see the future."""
    px = market(EVENT_DAYS[:10])  # jumps only on the first 10 Events
    calls = run_backtest(events(), px, CFG)
    late = [c for c in calls if c.occurred_on >= EVENT_DAYS[10].date().isoformat()]
    assert late and not all(c.hit for c in late)


def test_save(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    calls = run_backtest(events(), market(EVENT_DAYS), CFG)
    save_backtest(conn, calls)
    assert conn.execute("SELECT COUNT(*) FROM backtest").fetchone()[0] == len(calls)


def test_live_recommendations_get_scored_after_their_horizon(tmp_path):
    from tremor.analysis import analyze_event
    from tremor.events import save_events
    from tremor.prices import update_prices
    from tremor.recommend import recommend, save_recommendations
    from tremor.scoring import score_live

    px = market(EVENT_DAYS)
    evs = events()
    target = evs[-1]  # its window finished long before the synthetic data ends
    a = analyze_event(target, evs, px, CFG)
    recs = recommend(a, {e.id: e for e in evs}, None)
    conn = connect(tmp_path / "t.sqlite")
    save_events(conn, evs)
    save_recommendations(conn, recs)
    assert score_live(conn, px, CFG) == sum(r.exists for r in recs) > 0
    assert score_live(conn, px, CFG) == 0  # already scored
    hit = conn.execute("SELECT hit FROM rec_scores").fetchone()[0]
    assert hit == 1
