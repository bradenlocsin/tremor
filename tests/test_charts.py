import pandas as pd

from tremor.charts import plot_study, save
from tremor.config import load_config
from tremor.event_study import study
from tremor.events import Event

from tests.test_event_study import EVENT_DAYS, make_prices

CFG = load_config().event_study


def test_chart_renders_both_themes(tmp_path):
    px = make_prices(EVENT_DAYS)
    evs = [Event(f"e{i}", "t", "shipping_attack", "red_sea", d.date())
           for i, d in enumerate(EVENT_DAYS)]
    results = [study(px, evs, "ASSET", "SPY", CFG), study(px, evs[:1], "ASSET", "SPY", CFG)]
    for theme in ("light", "dark"):
        out = save(plot_study(results, "test", {"ASSET": "x"}, theme), tmp_path / f"{theme}.png")
        assert out.stat().st_size > 10_000
    assert isinstance(results[0].mean_car, pd.Series)
