"""Headline-screen every not-yet-screened Red Sea Candidate below rank 10 (ADR-0031, deep pass).
Resumable: already-screened URLs are skipped. Approved 2026-11-20 with the Jev budget raised to ~$5.50."""
from tremor import jev
from tremor.config import load_config, load_dotenv
from tremor.refine import pick_candidates
from tremor.storage import connect
from tremor.taxonomy import default_taxonomy

load_dotenv()
cfg = load_config()
conn = connect(cfg.storage_path)
ver = default_taxonomy().first_slice().version
done = set(jev.answers(conn, "screen"))
seen, todo = set(), []
for c in pick_candidates(conn, "red_sea", 10**6, taxonomy_version=ver):
    u = c["source_url"]
    if c["rk"] > 10 and u not in done and u not in seen:
        seen.add(u)
        todo.append((u, jev.screen_state(c)))
print(f"deep screen: {len(todo):,} URLs, about ${len(todo) * 3.2e-5:.2f}", flush=True)
print(jev.run(conn, "screen", todo, workers=16, log=lambda m: print(m, flush=True)), flush=True)
