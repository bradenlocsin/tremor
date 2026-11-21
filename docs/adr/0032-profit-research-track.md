# 32. Profit research track: trade rules found on discovery data, confirmed on a locked holdout

Date: 2026-11-20
Status: Accepted. Written before any trade rule has been tested.

## Context

The event study (ADR-0010) and the pre-registered shock tests (ADR-0031) ask whether markets react. This track asks whether a person could have made money from it after costs, entering only once the news was known. The search will be wide: many assets, horizons and filters. A wide search finds lucky rules, so the protections below are fixed before the search starts.

What earlier work suggests, which shapes where we look:
- LLM-read news predicts 1–2 day drift in stocks, strongest in small, illiquid firms, and the edge shrinks as more people use LLMs (Lopez-Lira and Tang). The liquid ETFs in v1 (BNO, GLD) are the hardest place to find drift; small shipping stocks are the most promising.
- Oil reacts strongly to geopolitical news but the move does not keep going; futures tend to overstate the expected change during conflicts. That points to fading oil spikes, not chasing them.
- Shipping firms gained value from the Red Sea detours, and fell sharply when carriers announced a return (ZIM fell up to 18% in one day). De-escalation news can move prices as much as attacks do.

## Decision

1. **Holdout locked.** Every Event or trade dated on or after **2025-11-20** is holdout. Discovery uses 2015-01-01 to 2025-11-19. The research code refuses holdout dates unless asked for the final confirmation run, and that run is logged.
2. **Every trial is logged.** Each rule evaluated on discovery data (asset, horizon, filter, direction, cost) is written to `alpha_trials`, including failures. The count of trials feeds the Deflated Sharpe ratio, so a rule found after 500 tries must clear a higher bar than one found after 5.
3. **No look-ahead.** A trade enters at the open of the first trading day after the day the article was first seen by GDELT (`date_added`). Day-0 moves before that are not available to the strategy. Exits are at a close.
4. **Costs on every trade.** One-way: 5 bp for large ETFs, 15 bp for single large-cap stocks, 30 bp for small shipping stocks, BDRY and BWET.
5. **Promotion bar.** A rule goes to the holdout only if, on discovery data: at least 20 trades, positive mean after costs, Deflated Sharpe probability ≥ 0.9. It passes the holdout if its mean after costs is positive with the same sign and at least half its discovery size. Passed rules go to paper trading on the live feed for 3 months before any real money.
6. **Look-ahead in the models themselves.** Codex, Gemini and Jev were trained on data that overlaps the history, so their labels may carry hindsight. Only paper trading on new events is free of this, which is why it is the last gate.

## Asset universe for research

v1 Assets plus: USO, XLE; tanker stocks FRO, STNG, INSW, DHT, TNK; container lines ZIM, MATX, DAC, GSL; tanker freight BWET; defense LMT, RTX, NOC. Prices from yfinance (personal, non-commercial use), with opens and closes, stored apart from the production prices.

## Rule families searched (fixed 2026-11-20, before the first run)

- **Drift:** after an Episode start of a type, long or short an asset for 1, 2, 5, 10 or 20 days, with or without a SPY hedge.
- **Severity filters:** the same, only for Episode starts Jev flags as `vessel_damaged`, `energy_target` or `escalation`.
- **Fade:** the spike is the asset's close on the day the news was known, over its close the day before the Event. If the spike is at least 2% (or 4%), trade against it from the next open for 1, 2, 5 or 10 days, with or without the hedge.
- **Intensity regime:** hold an asset (open to open) while the count of Events of a type known in the last 10 (or 20) trading days is above 1x (or 2x) its average over the prior year. Each day's position uses only Events known the day before. Daily Sharpe, so these trials form their own deflation pool (`discovery-daily`, at least 250 days).
- **De-escalation:** later, once ceasefire and route-reopening Events are tracked.

The first full search is 7,200 per-trade and 240 daily rules. A rule's latest run is its trial, so rerunning the search doesn't double-count.

Promotion and the holdout run are mechanical: every rule that clears the bar is confirmed, and none is picked by hand. That is why the ADR-0031 shock tests, which do use the whole history, can't steer which rules reach the holdout.
