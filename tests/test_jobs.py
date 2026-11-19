import sqlite3

from tremor.jobs import backup
from tremor.storage import connect


def test_backup_is_a_readable_copy_and_rotates(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    conn.execute("INSERT INTO assets_meta VALUES ('AAA', '2020-01-01')")
    conn.commit()
    dest = backup(conn, tmp_path / "backups")
    copy = sqlite3.connect(dest)
    assert copy.execute("SELECT ticker FROM assets_meta").fetchone() == ("AAA",)
    for i in range(9):
        (tmp_path / "backups" / f"tremor-2020010{i}.sqlite").write_bytes(b"")
    backup(conn, tmp_path / "backups", keep=3)
    assert len(list((tmp_path / "backups").glob("tremor-*.sqlite"))) == 3
