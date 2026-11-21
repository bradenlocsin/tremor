import sqlite3
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tremor import paper
from tremor.paper import Spec


def _px():
    idx = pd.bdate_range("2026-12-01", periods=30)
    c = pd.DataFrame({"BNO": np.linspace(100, 129, 30), "SPY": np.full(30, 500.0)}, index=idx)
    o = c - 0.5
    return o, c


def _sig(known="2026-12-03", occurred="2026-12-03", key="u1"):
    return {"key": key, "known_on": date.fromisoformat(known),
            "occurred_on": date.fromisoformat(occurred)}


def test_order_enters_after_its_day_and_closes_after_hold():
    conn = sqlite3.connect(":memory:")
    o, c = _px()
    paper.activate(conn, "r1", Spec("start:shipping_attack", "BNO", 3), "test", date(2026, 12, 1))
    assert paper.generate(conn, {"start:shipping_attack": [_sig()]}, c, date(2026, 12, 3)) == 1
    paper.fill(conn, o, c)
    row = paper.ledger(conn).iloc[0]
    assert row["entry_date"] == "2026-12-04" and row["exit_date"] == "2026-12-08"
    assert row["status"] == "closed" and row["ret"] > 0


def test_signals_before_activation_are_ignored_and_orders_are_idempotent():
    conn = sqlite3.connect(":memory:")
    _, c = _px()
    paper.activate(conn, "r1", Spec("s", "BNO", 3), "test", date(2026, 12, 10))
    assert paper.generate(conn, {"s": [_sig("2026-12-03")]}, c, date(2026, 12, 11)) == 0
    assert paper.generate(conn, {"s": [_sig("2026-12-10")]}, c, date(2026, 12, 11)) == 1
    assert paper.generate(conn, {"s": [_sig("2026-12-10")]}, c, date(2026, 12, 12)) == 0


def test_orders_cannot_be_edited_or_deleted_and_the_chain_checks():
    conn = sqlite3.connect(":memory:")
    _, c = _px()
    paper.activate(conn, "r1", Spec("s", "BNO", 3), "test", date(2026, 12, 1))
    paper.generate(conn, {"s": [_sig(key="a"), _sig("2026-12-04", key="b")]}, c,
                   date(2026, 12, 5))
    assert paper.chain_ok(conn)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE paper_orders SET direction = -1")
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("DELETE FROM paper_orders")


def test_fade_trades_against_the_spike():
    conn = sqlite3.connect(":memory:")
    _, c = _px()  # BNO rises steadily, so a fade goes short
    paper.activate(conn, "f", Spec("s", "BNO", 2, kind="fade", threshold=0.01), "t",
                   date(2026, 12, 1))
    paper.generate(conn, {"s": [_sig("2026-12-08", "2026-12-04")]}, c, date(2026, 12, 8))
    assert conn.execute("SELECT direction FROM paper_orders").fetchone()[0] == -1
