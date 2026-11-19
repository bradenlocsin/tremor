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


def test_usage_limit_stops_the_run_cleanly(tmp_path):
    from tremor.panel import CodexUsageLimit

    def limited(prompt, schema, model):
        raise CodexUsageLimit("You've hit your usage limit. Try again at 2:44 PM.")

    conn = seeded_db(tmp_path)
    stats = refine_candidates(conn, CFG, TAX, CodexRefiner(codex=limited),
                              fetch=lambda u: ARTICLE, log=lambda m: None, workers=2)
    assert "usage limit" in stats["stopped"] and stats["errors"] == 0
    assert conn.execute("SELECT COUNT(*) FROM candidates WHERE status != 'new'").fetchone()[0] == 0


def test_agy_refiner_labels_its_model():
    from tremor.codex_refine import AgyRefiner

    r = AgyRefiner(codex=fake_codex)
    assert r.model == "agy:gemini-3.8-flash-high" and r.free
    out = r.refine_batch("sys", ["a", "b"])
    assert "agy returned 0" in str(out[1][0])


def test_run_agy_parses_output_and_detects_quota(monkeypatch):
    import json
    import subprocess

    import pytest

    from tremor.panel import CodexUsageLimit, run_agy

    def fake_run(stdout, stderr="", code=0):
        return lambda *a, **k: subprocess.CompletedProcess(a, code, stdout, stderr)

    ok = json.dumps({"status": "SUCCESS", "structured_output": {"results": []}})
    monkeypatch.setattr(subprocess, "run", fake_run(ok))
    assert run_agy("p", {}) == {"results": []}
    monkeypatch.setattr(subprocess, "run", fake_run("", "429 RESOURCE_EXHAUSTED: quota", 1))
    with pytest.raises(CodexUsageLimit):
        run_agy("p", {})
    empty = json.dumps({"status": "SUCCESS", "response": ""})  # gave up after a denied tool call
    monkeypatch.setattr(subprocess, "run", fake_run(empty))
    with pytest.raises(RuntimeError, match="agy exited 0"):
        run_agy("p", {})


def test_oldest_first_reverses_the_order(tmp_path):
    from tremor.refine import pick_candidates

    conn = seeded_db(tmp_path)
    new = [c["event_date"] for c in pick_candidates(conn, "red_sea", 3)]
    old = [c["event_date"] for c in pick_candidates(conn, "red_sea", 3, oldest_first=True)]
    assert new == sorted(new, reverse=True) and old == sorted(old)
