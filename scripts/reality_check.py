"""White's Reality Check for the ADR-0032 search (data-snooping test).

Reruns the whole per-trade search (every signal set, asset, hold, hedge, direction, and the fade
rules) with each signal set's dates replaced by the same number of random discovery-period
trading days, many times. The p-value is the share of random searches whose best rule (n >= 20)
reaches the real search's best t-statistic. Discovery data only; logs no trials.

usage: uv run python scripts/reality_check.py [draws] [workers]
"""
import json
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from tremor import alpha, jev
from tremor.config import load_config
from tremor.events import load_events
from tremor.storage import connect

DRAWS = int(sys.argv[1]) if len(sys.argv) > 1 else 200
WORKERS = int(sys.argv[2]) if len(sys.argv) > 2 else 8
HOLDS, FADE_HOLDS, THRESH = (1, 2, 5, 10, 20), (1, 2, 5, 10), (0.02, 0.04)

cfg = load_config()
conn = connect(cfg.storage_path)
OPENS, CLOSES = alpha.load_ohlc(conn)
SETS = {k: v for k, v in alpha.signal_sets(conn, load_events(conn, region="red_sea"), CLOSES.index,
                                           cfg.event_study.episode_gap_trading_days,
                                           jev.answers(conn, "features")).items()
        if not k.startswith("all:")}
ASSETS = [a for a in alpha.RESEARCH_TICKERS if a != "SPY"]
CAL = CLOSES["SPY"].dropna().index
CAL = CAL[(CAL.date >= alpha.DISCOVERY_START) & (CAL.date < alpha.HOLDOUT_START)]


def t_of(rets):
    s = alpha.summarize(np.asarray(rets))
    return s["t"] if s["t"] is not None and s["n"] >= 20 else None


def best_t(sets):
    best = -np.inf
    for name, pairs in sets.items():
        known = [k for _, k in pairs]
        for a in ASSETS:
            for h in HOLDS:
                for hedge in (False, True):
                    for d in (1, -1):
                        t = t_of(alpha.trades(known, OPENS, CLOSES, alpha.Rule(name, a, h, d, hedge))["ret"])
                        if t is not None:
                            best = max(best, t)
                    if h in FADE_HOLDS:
                        for th in THRESH:
                            t = t_of(alpha.fade_trades(pairs, OPENS, CLOSES, a, h, th, hedge)["ret"])
                            if t is not None:
                                best = max(best, t)
    return best


def draw(seed):
    rng = np.random.default_rng(seed)
    fake = {}
    for name, pairs in SETS.items():
        idx = rng.choice(len(CAL), min(len(pairs), len(CAL)), replace=False)
        fake[name] = [(CAL[i].date(), CAL[i].date()) for i in sorted(idx)]
    return best_t(fake)


if __name__ == "__main__":
    real = best_t(SETS)
    print(f"real search best t = {real:.2f}", flush=True)
    with ProcessPoolExecutor(WORKERS) as pool:
        maxes = []
        for i, m in enumerate(pool.map(draw, range(DRAWS)), 1):
            maxes.append(m)
            if i % 20 == 0:
                print(f"  {i}/{DRAWS} draws, so far {np.mean(np.array(maxes) >= real):.1%} beat it", flush=True)
    maxes = np.array(maxes)
    out = {"real_best_t": real, "draws": DRAWS, "p_value": float(np.mean(maxes >= real)),
           "random_best_t": {"median": float(np.median(maxes)), "p90": float(np.percentile(maxes, 90)),
                             "p95": float(np.percentile(maxes, 95)), "max": float(maxes.max())}}
    print(json.dumps(out, indent=1))
    (cfg.storage_path.parent / "reality-check.json").write_text(json.dumps(out, indent=1))
