# 13. All-Python stack for v1

Date: 2026-11-18
Status: Accepted

## Context

The author is newer to coding and will build largely with Claude Code while learning. Finance and fintech roles expect Python. v1 needs a pipeline, event studies, LLM calls, a dashboard and a Passcode gate.

## Decision

- **Python** for everything: GDELT ingestion, LLM refinement, event studies (pandas + statsmodels), Recommendations.
- **Streamlit** for the dashboard (ADR-0009), with its password feature as the Passcode gate (ADR-0008).
- **SQLite or DuckDB** for storage. **A scheduled job** for pipeline refreshes.

## Alternatives rejected

- **FastAPI + Next.js + Postgres**: more polished and shows full-stack skill, but roughly twice the surface area for a newer developer.

## Consequences

- The quant engine and pipeline must stay separate from the Streamlit UI, so the UI can later be swapped (e.g. for Next.js) without touching them.
- Streamlit's look is limited, so the demo's polish comes from the event-study chart and copy.
- **Storage settled as SQLite (WAL mode)** during #2: the scheduled jobs write while the Streamlit app reads, and DuckDB allows only one writing process at a time. Analysis happens in pandas, so DuckDB's speed isn't needed at this data size.
- Pinned to Python 3.12 (via uv) for scientific-library compatibility.
