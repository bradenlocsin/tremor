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


def test_episode_start_candidates_only_queues_possible_starts(tmp_path):
    import json

    import pandas as pd

    import sqlite3

    conn = sqlite3.connect(tmp_path / "q.sqlite")
    conn.executescript(jev.SCHEMA + """
        CREATE TABLE events (event_type TEXT, region TEXT, occurred_on TEXT);
        CREATE TABLE candidates (source_url TEXT, region TEXT, status TEXT, event_date TEXT);
        INSERT INTO events VALUES ('shipping_attack', 'red_sea', '2024-01-15');""")
    cal = pd.bdate_range("2024-01-01", "2024-03-29")
    def screen(p):  # real screen answers have no main_news (headline only)
        return {k: v for k, v in p.items() if k in jev.SCREEN}

    yes = screen(probs(incident=0.9, in_region=0.9, ship_attacked=0.9))
    cands = {"two-days-after": "2024-01-17", "a-month-after": "2024-02-20",
             "day-before": "2024-01-12", "not-an-event": "2024-03-01"}
    for url, d in cands.items():
        conn.execute("INSERT INTO candidates VALUES (?, 'red_sea', 'new', ?)", (url, d))
        p = yes if url != "not-an-event" else screen(probs())
        conn.execute("INSERT INTO jev_answers VALUES (?, 'screen', 'm', ?, 1, 'now')",
                     (url, json.dumps(p)))
    got = set(jev.episode_start_candidates(conn, cal, gap=10))
    assert got == {"a-month-after", "day-before"}  # new Episode; earlier day 0
