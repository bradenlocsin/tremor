import re

from tests.test_refine import ARTICLE, CFG, TAX, seeded_db
from tremor.codex_refine import CodexRefiner
from tremor.refine import refine_candidates


def fake_codex(prompt, schema, model):
    ids = sorted({int(x) for x in re.findall(r"=== ITEM (\d+) ===", prompt)})
    return {"results": [{"id": i, "is_real_event": True, "noise_reason": "",
                         "event_type": "shipping_attack", "in_region": True, "title": "t",
                         "occurred_on": "2023-11-19", "actors": ["Houthis"], "severity": 9,
                         "summary": "s", "affected_assets": []} for i in ids if i != 1]}


def test_codex_refiner_batches_and_flags_missing_items():
    out = CodexRefiner(codex=fake_codex).refine_batch("sys", ["a", "b", "c"])
    assert out[0][0].severity == 5 and out[0][0].noise_reason is None  # clamped, "" → None
    assert isinstance(out[1][0], RuntimeError) and out[2][1].usd == 0


def test_codex_refiner_runs_in_the_pipeline(tmp_path):
    conn = seeded_db(tmp_path)
    stats = refine_candidates(conn, CFG, TAX, CodexRefiner(codex=fake_codex),
                              fetch=lambda u: ARTICLE, log=lambda m: None, workers=2)
    assert stats["events"] >= 1 and stats["events"] + stats["errors"] + stats["rejected"] > 1
    assert conn.execute("SELECT DISTINCT model FROM events WHERE origin='gdelt'").fetchall() == \
        [("codex:gpt-6.2-sol",)]
