import json

from tremor.config import load_config
from tremor.events import load_events
from tremor.gdelt import ensure_schema, parse_rows, save_candidates
from tremor.refine import (
    FakeRefiner, Usage, fetch_article, headline_from_url, html_to_text, pick_candidates,
    refine_candidates, spent,
)
from tremor.storage import connect
from tremor.taxonomy import load_taxonomy

from tests.test_gdelt import row

CFG = load_config()
TAX = load_taxonomy().first_slice()
ARTICLE = "<html><title>Houthis seize ship</title><body><script>x()</script>" + (
    "<p>Houthi forces boarded and seized the cargo vessel Galaxy Leader in the Red Sea on Sunday.</p>"
    * 10
) + "</body></html>"


def seeded_db(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    ensure_schema(conn)
    lines = [
        row("v1", "181", 15.0, 42.3, "https://n.example/houthis-seize-cargo-ship", "1"),
        row("v1", "181", 15.0, 42.3, "https://n.example/houthis-seize-cargo-ship", "2"),  # same URL
        row("v1", "195", 15.0, 42.3, "https://n.example/opinion-why-ships-matter", "3"),
    ]
    save_candidates(conn, parse_rows("\n".join(lines), "v1", TAX), "v1/20231119")
    return conn


def test_html_to_text_skips_scripts_and_keeps_title():
    title, text = html_to_text(ARTICLE)
    assert title == "Houthis seize ship"
    assert "x()" not in text and "Galaxy Leader" in text


def test_fallback_chain_ends_in_lower_fidelity():
    live = fetch_article("https://n.example/a", "2023-11-19", fetch=lambda u: ARTICLE)
    assert live.path == "live" and live.fidelity == "full"
    dead = fetch_article("https://n.example/houthis-seize-cargo-ship.html", "2023-11-19",
                         fetch=lambda u: None)
    assert dead.path == "gdelt-only" and dead.fidelity == "lower"
    assert dead.title == "houthis seize cargo ship"


def test_headline_from_url():
    assert headline_from_url("https://x.com/news/2023/11/19/red-sea-tanker-hit-12345") == \
        "red sea tanker hit"


def test_pick_one_row_per_url(tmp_path):
    conn = seeded_db(tmp_path)
    picked = pick_candidates(conn, "red_sea", per_day_per_type=5)
    assert len(picked) == 2  # two distinct URLs
    assert {p["source_url"] for p in picked} == {
        "https://n.example/houthis-seize-cargo-ship", "https://n.example/opinion-why-ships-matter"
    }


def test_refine_saves_events_rejects_noise_and_marks_candidates(tmp_path):
    conn = seeded_db(tmp_path)
    stats = refine_candidates(conn, CFG, TAX, FakeRefiner(), fetch=lambda u: ARTICLE, log=lambda m: None)
    assert stats == {"events": 1, "rejected": 1, "skipped_budget": 0, "errors": 0}
    (ev,) = load_events(conn)
    assert ev.origin == "gdelt" and ev.event_type == "shipping_attack"
    assert ev.refinement_path == "live" and ev.fidelity == "full" and ev.model == "fake"
    statuses = dict(conn.execute("SELECT gdelt_id, status FROM candidates").fetchall())
    assert statuses == {"1": "refined", "2": "refined", "3": "rejected"}
    # a second run has nothing left to do
    again = refine_candidates(conn, CFG, TAX, FakeRefiner(), fetch=lambda u: ARTICLE, log=lambda m: None)
    assert again["events"] == again["rejected"] == 0


def test_budget_cap_stops_spending(tmp_path):
    conn = seeded_db(tmp_path)

    class Pricey(FakeRefiner):
        model = "claude-sonnet-5-5"

        def refine(self, system, prompt):
            r, _ = super().refine(system, prompt)
            return r, Usage(self.model, 1_000_000, 0)  # $2 per call, above the $2 daily cap

    stats = refine_candidates(conn, CFG, TAX, Pricey(), fetch=lambda u: ARTICLE, log=lambda m: None)
    assert stats["skipped_budget"] == 1  # first call spends the cap, second is skipped
    assert spent(conn, "refine") >= CFG.daily_llm_usd


def test_usage_cost_uses_model_prices():
    assert Usage("claude-haiku-5-5", 1_000_000, 1_000_000).usd == 0.60
    assert json.dumps(Usage("fake", 5, 5).usd) == "0.0"


def test_redirect_to_front_page_counts_as_dead():
    from tremor.refine import redirected_to_front_page
    assert redirected_to_front_page("https://khaleejtimes.com/news/2015/05/09/yemen-strike", "https://www.khaleejtimes.com/")
    assert redirected_to_front_page("https://a.com/x/y/z-story", "https://a.com/news")
    assert not redirected_to_front_page("https://a.com/x/y/story", "https://a.com/x/y/story")
    assert not redirected_to_front_page("http://a.com/2015/story-slug", "https://a.com/2015/story-slug")
