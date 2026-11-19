from datetime import date

from tremor.events import load_events, load_seed_events, save_events
from tremor.storage import connect


def test_seed_events_are_valid_red_sea_events():
    events = load_seed_events()
    assert len(events) >= 12
    assert {e.region for e in events} == {"red_sea"}
    assert {e.event_type for e in events} <= {
        "shipping_attack", "military_strike", "chokepoint_disruption"
    }
    assert all(e.source_url and e.license for e in events)


def test_events_round_trip_through_storage(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    seeds = load_seed_events()
    save_events(conn, seeds)
    save_events(conn, seeds)  # idempotent
    loaded = load_events(conn, event_type="shipping_attack", region="red_sea")
    assert len(loaded) == sum(e.event_type == "shipping_attack" for e in seeds)
    assert loaded[0].occurred_on == date(2023, 11, 19)
    assert loaded[0].actors == ("Houthis",)
