import importlib.util
from datetime import datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "codex_supervisor", Path(__file__).resolve().parents[1] / "scripts" / "codex_supervisor.py")
sup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sup)
NOW = datetime(2026, 11, 19, 11, 30)


def test_short_window_reset_today():
    w = sup.reset_time("CODEX_LIMIT: You've hit your usage limit. ... try again at 2:44 PM.", NOW)
    assert w == datetime(2026, 11, 19, 14, 44) and w - NOW < sup.WEEKLY_AFTER


def test_weekly_reset_with_a_date_is_flagged():
    w = sup.reset_time("try again on Nov 24th, 2026 9:05 AM.", NOW)
    assert w == datetime(2026, 11, 24, 9, 5) and w - NOW > sup.WEEKLY_AFTER


def test_time_earlier_than_now_means_tomorrow():
    assert sup.reset_time("try again at 9:00 AM", NOW) == datetime(2026, 11, 20, 9, 0)
    assert sup.reset_time("no time here", NOW) is None
