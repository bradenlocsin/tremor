# TREMOR

**Tracking Risk Events & Market Outcome Reactions.** TREMOR turns geopolitical events into evidence about how markets react, using classic event studies (market-model abnormal returns) over comparable past events, with AI handling event classification and explanation.

> Work in progress. First slice: the Red Sea / Bab-el-Mandeb, five ETFs. See the [issues](https://github.com/bradenlocsin/tremor/issues/1).

## First result

![Average cumulative abnormal returns after Red Sea shipping attacks](docs/charts/red-sea-shipping-attacks-light.png)

How did markets react in the 20 trading days after Red Sea shipping attacks, beyond what the overall market explains? Based on 6 hand-verified Events, too few to be statistically meaningful yet (the minimum is 8). The GDELT pipeline will supply the full history.

## Case study

**[The 2023–24 Red Sea crisis: what TREMOR would have said, and how it did](docs/case-study-red-sea.md)** (draft; back-test results pending)

![Red Sea shipping before and after the 2023–24 attacks](docs/charts/red-sea-chokepoints-light.png)

## Quick start

```bash
uv sync --extra dev        # install (Python 3.12)
uv run tremor info         # show configuration
uv run pytest -m "not network"

# data
uv run tremor prices                 # daily prices (yfinance)
uv run tremor seed                   # 12 hand-verified Red Sea Events
uv run tremor gdelt backfill         # GDELT Candidates 2015 → today (hours; resumable)
uv run tremor refine --backfill      # LLM refinement (needs ANTHROPIC_API_KEY)
uv run tremor recommend              # Recommendations for the latest Episodes
uv run tremor backtest               # Track record

# dashboard (passcode-protected)
TREMOR_PASSCODE=choose-one uv run streamlit run src/tremor/dashboard/app.py
```

## Docs

- [`GLOSSARY.md`](GLOSSARY.md): the project's vocabulary
- [`docs/adr/`](docs/adr/): every design decision and why

_Not financial advice. TREMOR is an educational and portfolio project._
