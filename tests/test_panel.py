import re

from tremor import panel
from tremor.taxonomy import default_taxonomy

TAX = default_taxonomy().first_slice()


def items(n):
    return [{"id": i, "source_url": f"https://n.example/{i}", "text": "..."} for i in range(n)]


def label(i, real=True, etype="shipping_attack"):
    return {"id": i, "is_real_event": real, "event_type": etype if real else "none",
            "region": "red_sea"}


def fake_codex(skeptic_flips: set[int], judge_unsure: set[int]):
    calls = []

    def codex(prompt, schema):
        role = prompt.split(" on a three-person")[0].rsplit(" ", 1)[-1]
        ids = list(dict.fromkeys(int(x) for x in re.findall(r"\{\"id\": (\d+)", prompt)))
        calls.append((role, ids))
        if role == "LABELER":
            return {"labels": [{**label(i), "reason": "r"} for i in ids]}
        if role == "SKEPTIC":
            return {"reviews": [{**label(i, real=i not in skeptic_flips), "agrees": i not in
                                 skeptic_flips, "argument": "a"} for i in ids]}
        return {"rulings": [{**label(i, real=False), "confident": i not in judge_unsure,
                             "reason": "j"} for i in ids]}

    return codex, calls


def test_agreement_skips_the_judge():
    codex, calls = fake_codex(set(), set())
    out = panel.run_panel(TAX, items(12), codex=codex, log=lambda m: None)
    assert [r for r, _ in calls].count("JUDGE") == 0
    assert all(o["is_real"] is True and not o["disputed"] for o in out)
    assert {r for r, _ in calls} == {"LABELER", "SKEPTIC"} and len(calls) == 4  # 2 batches each


def test_disputes_go_to_the_judge_and_unsure_rulings_are_excluded():
    codex, calls = fake_codex({3, 7}, {7})
    out = {o["source_url"][-1]: o for o in panel.run_panel(TAX, items(10), codex=codex,
                                                           log=lambda m: None)}
    judged = [ids for role, ids in calls if role == "JUDGE"]
    assert judged == [[3, 7]]  # only the disputed items reach the judge
    assert out["3"]["is_real"] is False and out["3"]["event_type"] == "none"
    assert out["7"]["is_real"] is None  # judge not confident → unsure, excluded from scoring
    assert out["1"]["is_real"] is True and "panel agreed" in out["1"]["note"]


def test_labeler_never_sees_tremors_own_output():
    p, schema = panel.labeler_prompt(TAX, items(2))
    assert "refined" not in p.lower() and "haiku" not in p.lower()
    assert schema["properties"]["labels"]["items"]["additionalProperties"] is False


def test_real_event_outside_the_taxonomy_counts_as_noise():
    def codex(prompt, schema):
        ids = list(dict.fromkeys(int(x) for x in re.findall(r"\{\"id\": (\d+)", prompt)))
        key = "labels" if "LABELER" in prompt[:40] else "reviews"
        return {key: [{**label(i, etype="none"), "reason": "r", "agrees": True, "argument": "a"}
                      for i in ids]}

    out = panel.run_panel(TAX, items(1), codex=codex, log=lambda m: None)
    assert out[0]["is_real"] is False


def test_examples_come_only_from_the_teach_split(tmp_path):
    import json as _json

    from tremor import evalset
    from tremor.storage import connect

    conn = connect(tmp_path / "t.sqlite")
    evalset.ensure_schema(conn)
    for split, n in (("test", 5), ("teach", 5)):
        for i in range(n):
            url = f"https://n.example/{split}/{i}"
            cand = {"source_url": url, "region": "red_sea", "place": "Aden"}
            conn.execute("INSERT INTO eval_items (source_url, event_date, region, candidate,"
                         " sampled_at, split) VALUES (?, '2024-01-01', 'red_sea', ?, 'x', ?)",
                         (url, _json.dumps(cand), split))
            evalset.save_label(conn, url, i % 2 == 0, "shipping_attack" if i % 2 == 0 else "none",
                               "red_sea", False, note=f"panel agreed. labeler: {split} r | "
                               "skeptic: a", labeled_by="panel:x")
    picked = panel.select_examples(conn, n=16)
    assert len(picked) == 5 and all(p["summary"] == "teach r" for p in picked)
    assert sum(p["keep"] for p in picked) == 3


def test_examples_block_reads_the_file(tmp_path):
    from tremor.refine import examples_block

    f = tmp_path / "ex.json"
    f.write_text('[{"place": "Aden", "summary": "s", "why": "w", "is_real_event": true,'
                 ' "event_type": "shipping_attack", "in_region": true, "keep": true}]')
    text = examples_block(f)
    assert "1. GDELT place: Aden" in text and "real Event, shipping_attack" in text
    assert examples_block(tmp_path / "missing.json") == ""


def test_missing_judge_ruling_is_unsure_not_agreed():
    codex, _ = fake_codex({2}, set())

    def no_rulings(prompt, schema):
        return {"rulings": []} if prompt.startswith("You are the JUDGE") else codex(prompt, schema)

    out = {o["source_url"][-1]: o for o in panel.run_panel(TAX, items(4), codex=no_rulings,
                                                           log=lambda m: None)}
    assert out["2"]["is_real"] is None and "no ruling" in out["2"]["note"]


def test_foreign_and_duplicate_ids_are_ignored():
    def codex(prompt, schema):
        key = "labels" if prompt.startswith("You are the LABELER") else "reviews"
        rows = [{**label(0), "reason": "r", "agrees": True, "argument": "a"}] * 2  # duplicate 0
        rows.append({**label(99), "reason": "r", "agrees": True, "argument": "a"})  # foreign id
        rows.append({**label(1), "reason": "r", "agrees": True, "argument": "a"})
        return {key: rows}

    out = panel.run_panel(TAX, items(2), codex=codex, log=lambda m: None)
    assert out[0]["is_real"] is None and "incomplete" in out[0]["note"]
    assert out[1]["is_real"] is True


def test_story_keys_match_syndicated_copies():
    a = panel.story_keys("https://www.news.com.au/x/news-story/99228f3ece9d3a5850eda8a2742df723",
                         "Houthi rebels seize Emirati ship Rwabee off Yemen")
    b = panel.story_keys("https://www.heraldsun.com.au/y/news-story/99228f3ece9d3a5850eda8a2742df723",
                         None)
    c = panel.story_keys("https://other.example/story", "Houthi rebels seize Emirati ship Rwabee "
                         "off Yemen")
    assert a & b and a & c
    assert not panel.story_keys("https://n.example/houthis-seize-ship", "Short")
