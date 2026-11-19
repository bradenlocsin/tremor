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
| #5 event-study engine | done | `tremor.event_study.study()`; 8 synthetic-data tests |

## Log

- 2026-11-19 (Claude): created this file and armed the Codex handoff watchdog (it fires after 90 minutes with no file changes in the repo). Starting #2.
- 2026-11-19 00:10 (Claude): #2 merged; #3 prices + cache done (yfinance, non-commercial tag).
- 2026-11-19 00:12 (Claude): #7 taxonomy (12 Event types, 6 Regions) done. CAMEO codes are from memory of the CAMEO codebook; verify against real GDELT rows in #8.
- 2026-11-19 00:14 (Claude): #4 seed Events done: 12 Red Sea Events, each date checked against Wikipedia (3 unverifiable ones dropped).
- 2026-11-19 00:15 (Claude): #5 event-study engine done (market model, AR/CAR, cross-sectional t-test, N>=8 rule, broadening, ETF start-date skips). On the 12 seeds every result is 'insufficient' (N=5-6), as expected.
