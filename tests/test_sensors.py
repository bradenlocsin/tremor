from datetime import date, timedelta

import pytest

from tremor import sensors
from tremor.storage import connect


def fake_fetch(portid, start, end):
    names = sensors.REGION_CHOKEPOINTS["red_sea"]
    rows, d = [], start
    while d <= min(end, date(2024, 3, 31)):
        # Bab el-Mandeb collapses from ~70/day to ~30/day after 2023-12-15
        n = 70 if portid == "chokepoint4" and d < date(2023, 12, 15) else 30 \
            if portid == "chokepoint4" else 50
        rows.append({"portid": portid, "portname": names[portid], "date": d.isoformat(),
                     "n_total": n, "n_tanker": 10, "n_container": 10, "n_dry_bulk": 10})
        d += timedelta(days=1)
    return rows


def test_recorder_is_incremental(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    first = sensors.record_chokepoints(conn, fetch=fake_fetch)
    assert first > 3 * 365
    again = sensors.record_chokepoints(conn, fetch=fake_fetch)
    assert again <= 3 * 15  # re-reads only the last two weeks per chokepoint
    lic = conn.execute("SELECT DISTINCT license FROM chokepoint_transits").fetchall()
    assert lic == [("non-commercial",)]


def test_context_detects_the_collapse(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    sensors.record_chokepoints(conn, fetch=fake_fetch)
    ctx = {c.portname: c for c in sensors.context(sensors.transits(conn), date(2024, 1, 20))}
    bab = ctx["Bab el-Mandeb Strait"]
    assert bab.recent_mean == 30 and bab.change < -0.4
    text = sensors.context_text(conn, "red_sea", date(2024, 1, 20))
    assert "Bab el-Mandeb Strait: 30 transits/day" in text and "IMF PortWatch" in text


@pytest.mark.network
def test_portwatch_real():
    rows = sensors.fetch_daily("chokepoint4", date(2023, 11, 10), date(2023, 11, 12))
    assert len(rows) == 3 and rows[0]["portname"] == "Bab el-Mandeb Strait"
