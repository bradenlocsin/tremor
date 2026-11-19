# Handoff log

Running log so any agent (Claude Code or Codex) can continue TREMOR's overnight build. **Read `AGENTS.md`, `GLOSSARY.md` and `docs/adr/` first.** Work is tracked as GitHub issues #1–#17 on `bradenlocsin/tremor`. #1 is the parent; respect the "blocked by" links.

## Ground rules (from the user, 2026-11-18)

- The user is asleep and consented to all needed actions: commits, pushes, branches, PRs and merges on `bradenlocsin/tremor`.
- If something stops working, note it here and move to another unblocked issue.
- **No Anthropic API key is set.** Build LLM steps behind an interface with a fake client and tests; real calls wait for a key (`ANTHROPIC_API_KEY`).
- Never commit secrets or data files (`data/` is gitignored).
- Workflow: one branch per issue (`issue-N-short-name`), PR into `main` with `Closes #N`, squash-merge once tests pass.
- After each step, append a line to the log below. That also signals the handoff watchdog that work is still happening.

## Status

| Issue | State | Notes |
|---|---|---|
| #2 skeleton | done (PR #18) | `uv sync --extra dev`, `uv run tremor info`, `uv run pytest -m "not network"` |
| #3 prices | done (PR #19) | `uv run tremor prices` fills `data/tremor.sqlite`; BDRY history starts 2018-03-22 |
| #7 taxonomy | done (PR #20) | `config/taxonomy.toml`; CAMEO codes need checking against real GDELT data in #8 |
| #4 seed Events | done (PR #21) | `uv run tremor seed`; `config/seed_events.toml` (12 verified Events) |
| #5 event-study engine | done (PR #22) | `tremor.event_study.study()`; 8 synthetic-data tests |
| #6 first chart | done (PR #23) | `uv run tremor chart --type shipping_attack`; PNGs in `docs/charts/` |
| #8 GDELT ingestion | done (PR #24) | `uv run tremor gdelt backfill` (resumable; first slice only unless `--all`), `uv run tremor gdelt pull` (hourly) |
| #9 LLM refinement | code merged (PR #25); issue reopened until a real run (needs API key) | `uv run tremor refine --fake` (dry run); with a key: `uv run tremor refine --backfill` |
| #11 Episodes | done (PR #26) | `tremor.episodes`, `tremor.analysis.analyze_event()` |
| #12 Recommendations | done (PR #27) | `uv run tremor recommend [--fake]`; switch: `[recommendations] enabled` in config |
| #13 back-test | done (PR #28) | `uv run tremor backtest`; needs refined Events to produce calls |
| #14 dashboard | done | `TREMOR_PASSCODE=x uv run streamlit run src/tremor/dashboard/app.py` |

## Log

- 2026-11-19 (Claude): created this file and armed the Codex handoff watchdog (it fires after 90 minutes with no file changes in the repo). Starting #2.
- 2026-11-19 00:10 (Claude): #2 merged; #3 prices + cache done (yfinance, non-commercial tag).
- 2026-11-19 00:12 (Claude): #7 taxonomy (12 Event types, 6 Regions) done. CAMEO codes are from memory of the CAMEO codebook; verify against real GDELT rows in #8.
- 2026-11-19 00:14 (Claude): #4 seed Events done: 12 Red Sea Events, each date checked against Wikipedia (3 unverifiable ones dropped).
- 2026-11-19 00:15 (Claude): #5 event-study engine done (market model, AR/CAR, cross-sectional t-test, N>=8 rule, broadening, ETF start-date skips). On the 12 seeds every result is 'insufficient' (N=5-6), as expected.
- 2026-11-19 00:17 (Claude): #6 first charts done (docs/charts/, light+dark), in README.
- 2026-11-19 00:19 (Claude): #8 GDELT ingestion done. Real-data check: Galaxy Leader hijack found on 2023-11-19 (code 181). Red Sea box tightened (taxonomy v2) after Sudan/Gaza noise. Full backfill starts next (background, log: data/backfill.log).
- 2026-11-19 00:23 (Claude): #9 refinement built (Claude via messages.parse + FakeRefiner, fallback chain, budget caps). BLOCKED for real runs: no ANTHROPIC_API_KEY. Dry run on 12 real URLs: 4 live / 5 wayback / 3 headline-only. GDELT backfill running (~4h, resumable: rerun 'uv run tremor gdelt backfill').
- 2026-11-19 00:25 (Claude): #11 Episodes done; Comparables are now Episode starts (tremor.analysis). #9 reopened: code merged, real refinement run waits on an API key.
- 2026-11-19 00:26 (Claude): #12 Recommendations done (deterministic stance/horizon/confidence, Sonnet rationale via messages.parse, downgrade-only, on/off switch). On seed data: correctly no Recommendations (N<8).
- 2026-11-19 00:28 (Claude): #13 back-test done (prices cut before each Event's day 0; a flip test proves no look-ahead). Real data: 0 calls until refined GDELT Events exist.
- 2026-11-19 00:31 (Claude): #14 dashboard done (Streamlit, passcode gate, Plotly CAR chart with hover, Recommendation cards, map, Track record page). Headless AppTest covers lock/unlock and page switching. Added live-Recommendation scoring (tremor.scoring) that #13's PR text promised.
