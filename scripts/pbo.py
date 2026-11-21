"""Probability of Backtest Overfitting via CSCV (Bailey, Borwein, López de Prado, Zhu 2017).

Builds a months x rules matrix of returns for the ADR-0032 per-trade search (each trade's return
booked in its exit month; 0 in months with no trade), splits the discovery months into S blocks,
and for every way of choosing half the blocks as in-sample: takes the best in-sample rule and
records where it ranks out of sample. PBO = share of splits where it lands below the median.
Discovery data only; logs no trials.
"""
import itertools
import json

import numpy as np
import pandas as pd

from tremor import alpha, jev
from tremor.config import load_config
from tremor.events import load_events
from tremor.storage import connect

S = 12
cfg = load_config()
conn = connect(cfg.storage_path)
O, C = alpha.load_ohlc(conn)
sets = {k: v for k, v in alpha.signal_sets(conn, load_events(conn, region="red_sea"), C.index,
                                           cfg.event_study.episode_gap_trading_days,
                                           jev.answers(conn, "features")).items()
        if not k.startswith("all:")}
months = pd.period_range(alpha.DISCOVERY_START, alpha.HOLDOUT_START, freq="M")[:-1]
cols = {}
for name, pairs in sets.items():
    known = [k for _, k in pairs]
    for a in [x for x in alpha.RESEARCH_TICKERS if x != "SPY"]:
        for h in (1, 2, 5, 10, 20):
            for hedge in (False, True):
                for d in (1, -1):
                    t = alpha.trades(known, O, C, alpha.Rule(name, a, h, d, hedge))
                    if len(t) >= 20:
                        m = t.groupby(pd.to_datetime(t["exit"]).dt.to_period("M"))["ret"].sum()
                        cols[f"{name}|{a}|{h}|{d}|{hedge}"] = m.reindex(months, fill_value=0.0)
M = pd.DataFrame(cols)
blocks = np.array_split(np.arange(len(M)), S)
logits, below = [], 0
for ins in itertools.combinations(range(S), S // 2):
    i_idx = np.concatenate([blocks[b] for b in ins])
    o_idx = np.concatenate([blocks[b] for b in range(S) if b not in ins])
    best = M.iloc[i_idx].mean().idxmax()          # best rule in-sample (mean monthly return)
    oos = M.iloc[o_idx].mean()
    w = (oos.rank(pct=True)[best])                 # its out-of-sample percentile
    below += w <= 0.5
    logits.append(np.log(w / (1 - w + 1e-12) + 1e-12))
n = len(logits)
out = {"rules": M.shape[1], "months": M.shape[0], "splits": n, "pbo": below / n,
       "median_oos_percentile_of_is_best": float(np.median([1 / (1 + np.exp(-l)) for l in logits]))}
print(json.dumps(out, indent=1))
(cfg.storage_path.parent / "pbo.json").write_text(json.dumps(out, indent=1))
