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
| #2 skeleton | starting | |

## Log

- 2026-11-19 (Claude): created this file and armed the Codex handoff watchdog (it fires after 90 minutes with no file changes in the repo). Starting #2.
