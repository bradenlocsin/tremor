from datetime import date

import pandas as pd
import pytest

from tremor.prices import YFinanceSource, first_trade_dates, load_prices, update_prices
from tremor.storage import connect


class FakeSource:
    name = "fake"
    license = "non-commercial"

    def __init__(self, data: dict[str, pd.Series]):
        self.data = data
        self.calls: list[tuple[str, date]] = []

    def fetch(self, ticker, start):
        self.calls.append((ticker, start))
        s = self.data[ticker]
        return s[[d >= start for d in s.index]]


def series(start: str, values: list[float]) -> pd.Series:
    days = pd.bdate_range(start, periods=len(values)).date
    return pd.Series(values, index=days)


def test_update_fetches_history_then_only_new_days(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    src = FakeSource({"AAA": series("2020-01-01", [1, 2, 3])})
    assert update_prices(conn, src, ["AAA"], history_start=date(2020, 1, 1)) == {"AAA": 3}

    src.data["AAA"] = series("2020-01-01", [1, 2, 3, 4, 5])
    assert update_prices(conn, src, ["AAA"]) == {"AAA": 2}
    # second call asked only for days after the last cached date
    assert src.calls[1] == ("AAA", date(2020, 1, 4))

    wide = load_prices(conn, ["AAA"])
    assert wide["AAA"].tolist() == [1, 2, 3, 4, 5]
    assert first_trade_dates(conn)["AAA"] == date(2020, 1, 1)


def test_provenance_and_license_are_stored(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    update_prices(conn, FakeSource({"AAA": series("2020-01-01", [1])}), ["AAA"])
    source, license_ = conn.execute("SELECT source, license FROM prices").fetchone()
    assert (source, license_) == ("fake", "non-commercial")


@pytest.mark.network
def test_yfinance_real_fetch():
    s = YFinanceSource().fetch("SPY", date(2024, 1, 2))
    assert len(s) > 100
    assert s.index[0] >= date(2024, 1, 2)
