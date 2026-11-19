from tremor import evalset
from tremor.config import load_config
from tremor.gdelt import ensure_schema, parse_rows, save_candidates
from tremor.refine import FakeRefiner, SPEND_SCHEMA
from tremor.storage import connect
from tremor.taxonomy import load_taxonomy

from tests.test_gdelt import row
from tests.test_refine import ARTICLE

CFG = load_config()
TAX = load_taxonomy().first_slice()


def db(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    ensure_schema(conn)
    conn.executescript(SPEND_SCHEMA)
    lines = [row("v1", "181", 15.0, 42.3, f"https://n.example/ship-seized-{i}", str(i))
             for i in range(6)]
    lines.append(row("v1", "195", 15.0, 42.3, "https://n.example/opinion-ships", "99"))
    save_candidates(conn, parse_rows("\n".join(lines), "v1", TAX), "v1/20231119")
    return conn


def test_sample_and_label_flow(tmp_path):
    conn = db(tmp_path)
    assert evalset.sample(conn, "red_sea", n=5) == 5
    assert evalset.sample(conn, "red_sea", n=5) == 2  # only unsampled URLs remain
    done, total = evalset.progress(conn)
    assert (done, total) == (0, 7)
    item = evalset.next_unlabeled(conn)
    evalset.save_label(conn, item["source_url"], True, "shipping_attack", "red_sea", False)
    assert evalset.progress(conn) == (1, 7)
    assert evalset.next_unlabeled(conn)["source_url"] != item["source_url"]


def test_score_counts_fields_and_skips_unsure(tmp_path):
    conn = db(tmp_path)
    evalset.sample(conn, "red_sea", n=10)
    for i in range(6):
        evalset.save_label(conn, f"https://n.example/ship-seized-{i}", True, "shipping_attack",
                           "red_sea", False)
    evalset.save_label(conn, "https://n.example/opinion-ships", False, "none", "red_sea", False)
    s = evalset.score(conn, CFG, TAX, FakeRefiner(), fetch=lambda u: ARTICLE)
    assert s.n == 7
    assert s.real_accuracy == 1.0 and s.type_accuracy == 1.0 and s.noise_rejection == 1.0
    # an unsure label is excluded from scoring
    evalset.save_label(conn, "https://n.example/opinion-ships", None, "none", "red_sea", False)
    assert evalset.score(conn, CFG, TAX, FakeRefiner(), fetch=lambda u: ARTICLE).n == 6
    assert conn.execute("SELECT COUNT(*) FROM eval_runs").fetchone()[0] == 2
