"""Headline-screen every Candidate of one Region with Jev (ADR-0031 applied to a new Region).

Answers are stored as kind "screen:<region>" so they never mix with the Red Sea screen, and the
in_region question uses that Region's description from the taxonomy. Resumable.
usage: uv run python scripts/jev_screen_region.py hormuz
"""
import sys

from tremor import jev
from tremor.config import load_config, load_dotenv
from tremor.storage import connect

region = sys.argv[1]
load_dotenv()
conn = connect(load_config().storage_path)
words = jev.region_text(region)
kind = f"screen:{region}"
done = set(jev.answers(conn, kind))
rows = conn.execute("SELECT source_url, MAX(actor1), MAX(actor2), MAX(place) FROM candidates"
                    " WHERE region = ? GROUP BY source_url", (region,)).fetchall()
todo = [(u, jev.screen_state({"source_url": u, "actor1": a1, "actor2": a2, "place": pl}, words))
        for u, a1, a2, pl in rows if u not in done]
print(f"{kind}: {len(todo):,} URLs to screen ({len(done):,} done), about ${len(todo) * 3.2e-5:.2f}",
      flush=True)
print(jev.run(conn, kind, todo, workers=16, log=lambda m: print(m, flush=True)), flush=True)
