from tremor.config import load_config
from tremor.storage import connect


def test_config_loads_first_slice_assets():
    cfg = load_config()
    assert cfg.benchmark == "SPY"
    assert [a.ticker for a in cfg.assets] == ["BNO", "GLD", "ITA", "BDRY", "UUP"]
    assert cfg.tickers[0] == "SPY"
    assert cfg.event_study.min_comparables == 8


def test_storage_creates_schema(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"prices", "assets_meta", "events"} <= tables


def test_tremor_db_env_overrides_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("TREMOR_DB", str(tmp_path / "x.sqlite"))
    assert load_config().storage_path == tmp_path / "x.sqlite"
