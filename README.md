# TREMOR

**Tracking Risk Events & Market Outcome Reactions.** TREMOR turns geopolitical events into evidence about how markets react, using classic event studies (market-model abnormal returns) over comparable past events, with AI handling event classification and explanation.

> Work in progress. First slice: the Red Sea / Bab-el-Mandeb, five ETFs. See the [issues](https://github.com/bradenlocsin/tremor/issues/1).

## Quick start

```bash
uv sync --extra dev        # install (Python 3.12)
uv run tremor info         # show configuration
uv run pytest -m "not network"
```

## Docs

- [`GLOSSARY.md`](GLOSSARY.md): the project's vocabulary
- [`docs/adr/`](docs/adr/): every design decision and why

_Not financial advice. TREMOR is an educational and portfolio project._
