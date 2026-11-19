import pytest

from tests.test_codex_refine import fake_codex
from tests.test_refine import ARTICLE, CFG, TAX, seeded_db
from tremor import audit
from tremor.codex_refine import AgyRefiner, CodexRefiner
from tremor.refine import refine_candidates


def test_kappa():
    assert audit.kappa([True, False] * 5, [True, False] * 5) == 1.0
    assert audit.kappa([True, True, False, False], [True, False, True, False]) == pytest.approx(0)


def test_audit_compares_checker_with_codex(tmp_path):
    conn = seeded_db(tmp_path)
    refine_candidates(conn, CFG, TAX, CodexRefiner(codex=fake_codex), fetch=lambda u: ARTICLE,
                      log=lambda m: None, workers=1)
    r = audit.run(conn, CFG, TAX, AgyRefiner(codex=fake_codex), n=10,
                  fetch=lambda u: ARTICLE, log=lambda m: None)
    assert r.n >= 1 and r.both_keep + r.only_codex + r.only_checker + r.neither == r.n
    assert conn.execute("SELECT COUNT(*) FROM audit_runs").fetchone()[0] == 1
