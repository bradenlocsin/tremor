from tests.test_evalset import ARTICLE, TAX, db
from tremor import evalset, jev


def probs(**kw):
    p = dict.fromkeys(jev.QUESTIONS, 0.02)
    return {**p, **kw}


def test_decide_is_a_truth_table():
    keep, kind = jev.decide(probs(incident=0.9, main_news=0.9, in_region=0.9, ship_attacked=0.95))
    assert keep and kind == "shipping_attack"
    assert not jev.decide(probs(incident=0.9, main_news=0.9, in_region=0.2, ship_attacked=0.95))[0]
    assert jev.decide(probs(incident=0.9, in_region=0.9))[1] == "none"
    assert jev.pass_on(probs(incident=0.5, main_news=0.6, in_region=0.4, land_strike=0.35))
    assert not jev.pass_on(probs(incident=0.9, in_region=0.9))


def test_score_jev_counts_and_reports_errors(tmp_path):
    conn = db(tmp_path)
    evalset.sample(conn, "red_sea", n=10)
    for i in range(6):
        evalset.save_label(conn, f"https://n.example/ship-seized-{i}", True, "shipping_attack",
                           "red_sea", False)
    evalset.save_label(conn, "https://n.example/opinion-ships", False, "none", "red_sea", False)

    def fake_judge(items, workers):
        out = [jev.Judgment(probs(incident=0.9, main_news=0.9, in_region=0.9, ship_attacked=0.9), "jev-x", 100)
               for _ in items]
        out[0] = RuntimeError("429")  # a failed call is skipped, never counted as "no"
        return out

    res = evalset.score_jev(conn, TAX, judge=fake_judge, fetch=lambda u: ARTICLE)
    assert res["n"] == 6 and res["tokens"] == 600
    assert res["prefilter"][0.3]["forwarded"] == 1.0


def test_background_mentions_are_not_kept():
    p = probs(incident=0.95, main_news=0.1, in_region=0.9, blockade=0.95)
    assert not jev.decide(p)[0] and not jev.pass_on(p)
