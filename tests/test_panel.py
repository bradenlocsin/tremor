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
