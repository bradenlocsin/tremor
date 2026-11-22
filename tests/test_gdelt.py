from datetime import datetime

from tremor.gdelt import COLUMNS, done_files, ensure_schema, parse_rows, save_candidates, v2_stamps_since
from tremor.storage import connect
from tremor.taxonomy import load_taxonomy

TAX = load_taxonomy()


def row(version: str, code: str, lat: float, lon: float, url: str, gid: str = "1") -> str:
    c = COLUMNS[version]
    cells = [""] * c["n"]
    cells[0], cells[1] = gid, "20231119"
    cells[c["added"]] = "20231119"
    cells[c["actor1"]], cells[c["actor2"]] = "HOUTHI", "SHIP"
    cells[c["code"]] = code
    cells[c["lat"]], cells[c["lon"]] = str(lat), str(lon)
    cells[c["mentions"]] = cells[c["sources"]] = cells[c["articles"]] = "3"
    cells[c["url"]] = url
    return "\t".join(cells)


def test_parse_keeps_only_matching_rows_in_regions():
    lines = [
        row("v1", "181", 15.0, 42.3, "https://x.com/houthis-hijack-cargo-ship", "1"),  # keep
        row("v1", "181", 48.8, 2.3, "https://x.com/hijack-ship-paris", "2"),  # no Region
        row("v1", "042", 15.0, 42.3, "https://x.com/visit-ship", "3"),  # code not in taxonomy
        row("v1", "195", 15.0, 42.3, "https://x.com/airstrike-on-hodeidah", "4"),  # strike, not ship
    ]
    cands = parse_rows("\n".join(lines), "v1", TAX)
    by_id = {c.gdelt_id: c for c in cands}
    assert set(by_id) == {"1", "4"}
    assert "shipping_attack" in by_id["1"].candidate_types
    assert "shipping_attack" not in by_id["4"].candidate_types
    assert by_id["1"].region == "red_sea" and by_id["1"].event_date == "2023-11-19"


def test_v2_layout_parses_too():
    cands = parse_rows(row("v2", "195", 12.6, 43.3, "https://x.com/tanker-struck"), "v2", TAX)
    assert len(cands) == 1 and cands[0].lat == 12.6


def test_save_is_idempotent_and_records_files(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    ensure_schema(conn)
    cands = parse_rows(row("v1", "181", 15.0, 42.3, "https://x.com/ship"), "v1", TAX)
    save_candidates(conn, cands, "v1/20231119")
    save_candidates(conn, cands, "v1/20231119")
    assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
    assert done_files(conn) == {"v1/20231119"}


def test_v2_stamps():
    now = datetime(2026, 11, 19, 7, 40)
    assert v2_stamps_since(datetime(2026, 11, 19, 6, 45), now) == [
        "20261119070000", "20261119071500"
    ]
    assert len(v2_stamps_since(None, now)) == 13  # 3 hours back, inclusive


def test_first_slice_filter_and_tight_red_sea_box():
    fs = TAX.first_slice()
    assert {r.id for r in fs.regions} == {"red_sea"}
    khartoum = row("v1", "190", 15.6, 32.5, "https://x.com/sudan-clashes")
    gaza = row("v1", "190", 31.5, 34.45, "https://x.com/gaza-strike")
    assert parse_rows("\n".join([khartoum, gaza]), "v1", fs) == []


def test_stale_candidates_are_not_picked(tmp_path):
    from tremor.refine import pick_candidates
    conn = connect(tmp_path / "t.sqlite")
    ensure_schema(conn)
    fresh = row("v1", "181", 15.0, 42.3, "https://x.com/ship-seized-today", "1")
    stale = row("v1", "181", 15.0, 42.3, "https://x.com/ship-seized-back-then", "2").replace(
        "\t20231119\t", "\t20050101\t", 1)
    save_candidates(conn, parse_rows(fresh + "\n" + stale, "v1", TAX), "v1/20231119")
    urls = {c["source_url"] for c in pick_candidates(conn, "red_sea", 5)}
    assert urls == {"https://x.com/ship-seized-today"}


def test_a_new_region_backfills_days_already_done_for_the_red_sea(monkeypatch):
    import sqlite3
    from datetime import date

    from tremor import gdelt

    conn = sqlite3.connect(":memory:")
    gdelt.ensure_schema(conn)
    conn.execute("INSERT INTO gdelt_files VALUES ('v1/20190601', 5, 'x')")
    seen = []
    monkeypatch.setattr(gdelt, "_process", lambda n, u, v, t: (seen.append(n), (n, []))[1])
    gdelt.backfill(conn, None, date(2019, 6, 1), date(2019, 6, 2), workers=1, log=lambda m: None)
    assert seen == ["v1/20190602"]
    seen.clear()
    gdelt.backfill(conn, None, date(2019, 6, 1), date(2019, 6, 2), workers=1, log=lambda m: None,
                   scope="hormuz")
    assert sorted(seen) == ["v1/20190601#hormuz", "v1/20190602#hormuz"]
