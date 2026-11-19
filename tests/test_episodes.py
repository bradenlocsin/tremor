from datetime import date

import pandas as pd

from tremor.episodes import build_episodes, episode_of, episode_starts
from tremor.events import Event, load_seed_events

CAL = pd.bdate_range("2015-01-01", "2025-12-31")


def ev(i, d, etype="shipping_attack", region="red_sea"):
    return Event(id=f"e{i}", title="t", event_type=etype, region=region,
                 occurred_on=date.fromisoformat(d))


def test_burst_becomes_one_episode_and_gap_starts_a_new_one():
    evs = [
        ev(1, "2024-01-02"), ev(2, "2024-01-05"), ev(3, "2024-01-15"),  # within 10 trading days
        ev(4, "2024-03-01"),                                            # far later: new Episode
        ev(5, "2024-01-03", etype="military_strike"),                   # other type: own Episode
    ]
    eps = build_episodes(evs, CAL, gap=10)
    assert [(ep.event_type, ep.size) for ep in eps] == [
        ("shipping_attack", 3), ("military_strike", 1), ("shipping_attack", 1)
    ]
    assert [e.id for e in episode_starts(eps)] == ["e1", "e5", "e4"]
    assert episode_of("e3", eps).first.id == "e1"


def test_chain_of_close_events_stays_one_episode():
    # each event within 10 trading days of the previous one, though the span is much longer
    days = pd.bdate_range("2024-01-01", periods=10, freq="8B")
    evs = [ev(i, d.date().isoformat()) for i, d in enumerate(days)]
    (ep,) = build_episodes(evs, CAL, gap=10)
    assert ep.size == 10 and ep.start == days[0].date()


def test_seed_events_are_all_separate_episodes():
    seeds = load_seed_events()
    eps = build_episodes(seeds, CAL, gap=10)
    assert len(eps) == len(seeds)


def test_analysis_uses_only_earlier_episode_starts():
    from tremor.analysis import analyze_event
    from tremor.config import load_config
    from tests.test_event_study import EVENT_DAYS, make_prices

    cfg = load_config()
    px = make_prices(EVENT_DAYS).rename(columns={"ASSET": "BNO"})
    for a in cfg.assets:
        if a.ticker not in px:
            px[a.ticker] = px["BNO"]
    evs = [ev(i, d.date().isoformat()) for i, d in enumerate(EVENT_DAYS)]
    # a burst right after the last event: e100 joins the last Episode
    burst = ev(100, (EVENT_DAYS[-1] + pd.offsets.BDay(3)).date().isoformat())
    a = analyze_event(burst, evs + [burst], px, cfg)
    assert a.episode.first.id == f"e{len(EVENT_DAYS) - 1}"
    # Comparables are the Episode starts before the anchor: every earlier event
    assert a.results["BNO"].n == len(EVENT_DAYS) - 1
