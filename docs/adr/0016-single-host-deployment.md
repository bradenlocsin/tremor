# 16. One small always-on host for v1

Date: 2026-11-18
Status: Accepted

## Decision

Run v1 on a single small host (e.g. Railway or Fly.io, roughly $5–10/month): the Streamlit app, the hourly and daily jobs (ADR-0015), and the SQLite/DuckDB file on a persistent disk.

## Alternatives rejected

- **Streamlit Community Cloud + GitHub Actions cron + MotherDuck**: $0, but three services, secrets in three places, and more ways to fail. Too much to debug for a newer developer.

## Consequences

- The cost is about $5–10/month for hosting plus a few dollars of LLM spend, bounded by the daily cap.
- The database lives on one disk, so it needs a periodic backup.
