"""Command-line entry point: `tremor <command>`."""

from __future__ import annotations

import argparse
import json
import sys

from tremor.config import load_config, load_dotenv


def cmd_info(args: argparse.Namespace) -> int:
    cfg = load_config()
    print(f"storage:   {cfg.storage_path}")
    print(f"benchmark: {cfg.benchmark}")
    print("assets:    " + ", ".join(a.ticker for a in cfg.assets))
    print(f"models:    refinement={cfg.refinement_model}  rationale={cfg.rationale_model}")
    return 0


def cmd_prices(args: argparse.Namespace) -> int:
    from tremor.prices import YFinanceSource, first_trade_dates, update_prices
    from tremor.storage import connect

    cfg = load_config()
    conn = connect(cfg.storage_path)
    added = update_prices(conn, YFinanceSource(), cfg.tickers)
    firsts = first_trade_dates(conn)
    for t in cfg.tickers:
        print(f"{t:5} +{added[t]:5} rows   history from {firsts.get(t, '-')}")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from tremor.events import load_seed_events, save_events
    from tremor.storage import connect

    cfg = load_config()
    n = save_events(connect(cfg.storage_path), load_seed_events())
    print(f"loaded {n} seed Events")
    return 0


def cmd_chart(args: argparse.Namespace) -> int:
    from pathlib import Path

    from tremor.charts import plot_study, save
    from tremor.analysis import analyze_group
    from tremor.events import load_events
    from tremor.prices import load_prices
    from tremor.storage import connect
    from tremor.taxonomy import default_taxonomy

    cfg = load_config()
    tax = default_taxonomy()
    conn = connect(cfg.storage_path)
    prices = load_prices(conn, cfg.tickers)
    events = load_events(conn)
    by_asset = analyze_group(args.type, args.region, events, prices, cfg)
    results = [by_asset[a.ticker] for a in cfg.assets]
    title = f"{tax.event_type(args.type).name}s, {tax.region(args.region).name}: average CAR at Episode starts"
    names = {a.ticker: a.category for a in cfg.assets}
    out = Path(args.out)
    for theme in ("light", "dark"):
        path = out.with_name(f"{out.stem}-{theme}{out.suffix}")
        save(plot_study(results, title, names, theme), path)
        print(f"wrote {path}")
    return 0


def cmd_gdelt(args: argparse.Namespace) -> int:
    from datetime import date, timedelta

    from tremor import gdelt
    from tremor.storage import connect
    from tremor.taxonomy import default_taxonomy

    cfg = load_config()
    conn = connect(cfg.storage_path)
    gdelt.ensure_schema(conn)
    tax = default_taxonomy() if args.all else default_taxonomy().first_slice()
    if args.action == "backfill":
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
        print(f"backfilling GDELT 1.0 daily files {start} → {end}")
        print(f"kept {gdelt.backfill(conn, tax, start, end, workers=args.workers)} Candidates")
    elif args.action == "pull":
        print(f"kept {gdelt.pull_latest(conn, tax)} Candidates from GDELT 2.0")
    for region, types, n, urls in gdelt.candidate_counts(conn):
        print(f"{region:16} {types:60} {n:7} rows {urls:7} urls")
    return 0


def cmd_refine(args: argparse.Namespace) -> int:
    import os

    from tremor import gdelt
    from tremor.refine import ClaudeRefiner, FakeRefiner, refine_candidates
    from tremor.storage import connect
    from tremor.taxonomy import default_taxonomy

    cfg = load_config()
    conn = connect(cfg.storage_path)
    gdelt.ensure_schema(conn)
    if args.fake:
        refiner = FakeRefiner()
    elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        refiner = ClaudeRefiner(cfg.refinement_model)
    else:
        print("No Anthropic credentials found (set ANTHROPIC_API_KEY). Use --fake for a dry run.")
        return 2
    stats = refine_candidates(
        conn, cfg, default_taxonomy().first_slice(), refiner,
        purpose="backfill" if args.backfill else "refine",
        per_day_per_type=args.per_day, since=args.since, limit=args.limit,
    )
    print(stats)
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    import os

    from tremor.analysis import analyze_event, episodes_for
    from tremor.events import load_events
    from tremor.prices import load_prices
    from tremor.recommend import ClaudeExplainer, FakeExplainer, recommend, save_recommendations
    from tremor.storage import connect

    cfg = load_config()
    if not cfg.recommendations_enabled:
        print("Recommendations are switched off in config/tremor.toml (ADR-0004).")
        return 0
    conn = connect(cfg.storage_path)
    prices = load_prices(conn, cfg.tickers)
    events = load_events(conn)
    episodes = episodes_for(events, prices, cfg)
    if args.fake:
        explainer = FakeExplainer()
    elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        explainer = ClaudeExplainer(cfg.rationale_model)
    else:
        explainer = None
        print("(no Anthropic credentials: deterministic Recommendations only, no rationale)")
    by_id = {e.id: e for e in events}
    targets = [ep.first for ep in episodes][-args.latest:]
    for target in targets:
        analysis = analyze_event(target, events, prices, cfg, episodes)
        from tremor.sensors import context_text

        ctx = context_text(conn, target.region, target.occurred_on)
        recs = recommend(analysis, by_id, explainer, conn, context=ctx)
        save_recommendations(conn, recs)
        print(f"{target.occurred_on} {target.title[:70]}")
        for r in recs:
            if r.exists:
                print(f"   {r.asset:5} {r.stance:11} {r.horizon_days:2}d  CAR {r.mean_car*100:+.2f}%"
                      f"  N={r.n}  Confidence {r.confidence}")
            else:
                print(f"   {r.asset:5} no Recommendation: {r.no_rec_reason}")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from tremor.backtest import run_backtest, save_backtest, summarize
    from tremor.events import load_events
    from tremor.prices import load_prices
    from tremor.storage import connect

    cfg = load_config()
    conn = connect(cfg.storage_path)
    calls = run_backtest(load_events(conn), load_prices(conn, cfg.tickers), cfg)
    save_backtest(conn, calls)
    from tremor.scoring import score_live

    scored = score_live(conn, load_prices(conn, cfg.tickers), cfg)
    print(f"{len(calls)} back-tested calls (deterministic Stance/Confidence, no look-ahead); "
          f"{scored} live Recommendations newly scored")
    if calls:
        print(summarize(calls).to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    import os

    from tremor import evalset, gdelt
    from tremor.refine import SPEND_SCHEMA, ClaudeRefiner, FakeRefiner
    from tremor.storage import connect
    from tremor.taxonomy import default_taxonomy

    cfg = load_config()
    conn = connect(cfg.storage_path)
    gdelt.ensure_schema(conn)
    conn.executescript(SPEND_SCHEMA)
    if args.action == "sample":
        added = evalset.sample(conn, "red_sea", n=args.n, seed=args.seed, split=args.split)
        print(f"added {added} {args.split} items to the Eval set")
    elif args.action == "examples":
        from tremor import panel
        from tremor.refine import EXAMPLES_PATH

        evalset.ensure_schema(conn)
        picked = panel.select_examples(conn, n=args.n if args.n != 100 else 16)
        EXAMPLES_PATH.write_text(json.dumps(picked, indent=2, ensure_ascii=False) + "\n")
        kept = sum(e["keep"] for e in picked)
        print(f"wrote {len(picked)} worked examples ({kept} kept Events) to {EXAMPLES_PATH}")
    elif args.action == "panel":
        from tremor import panel

        model = args.model or panel.DEFAULT_MODEL
        tax = default_taxonomy().first_slice()
        evalset.ensure_schema(conn)
        print("fetching Eval set articles…")
        items = panel.gather(conn)
        print(f"running the Codex panel ({model}) on {len(items)} items…")
        for lab in panel.run_panel(tax, items, codex=lambda p, s: panel.run_codex(p, s, model)):
            evalset.save_label(conn, lab["source_url"], lab["is_real"], lab["event_type"],
                               lab["region"], duplicate=False, note=lab["note"],
                               labeled_by=f"panel:{model}")
    elif args.action == "score":
        if args.fake:
            refiner = FakeRefiner()
        elif os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            refiner = ClaudeRefiner(args.model or cfg.refinement_model)
        else:
            print("No Anthropic credentials found (set ANTHROPIC_API_KEY). Use --fake to test.")
            return 2
        s = evalset.score(conn, cfg, default_taxonomy().first_slice(), refiner)

        def fmt(x):
            return "–" if x is None else f"{x:.0%}"

        print(f"{s.run_id}: n={s.n}  real-vs-noise {fmt(s.real_accuracy)}  "
              f"Event type {fmt(s.type_accuracy)}  Region {fmt(s.region_accuracy)}  "
              f"noise rejected {fmt(s.noise_rejection)}")
        print(f"  pipeline: kept-Event precision {fmt(s.keep_precision)}  "
              f"recall {fmt(s.keep_recall)}")
    done, total = evalset.progress(conn)
    print(f"labeled {done} / {total}")
    return 0


def cmd_jobs(args: argparse.Namespace) -> int:
    from tremor import jobs

    {"hourly": jobs.hourly, "daily": jobs.daily}[args.which]()
    return 0


def cmd_scheduler(args: argparse.Namespace) -> int:
    from tremor.jobs import run_scheduler

    run_scheduler()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tremor", description="Tracking Risk Events & Market Outcome Reactions"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="show the loaded configuration").set_defaults(func=cmd_info)
    sub.add_parser("prices", help="fetch new daily prices into the cache").set_defaults(
        func=cmd_prices
    )
    sub.add_parser("seed", help="load the hand-entered seed Events").set_defaults(func=cmd_seed)
    chart = sub.add_parser("chart", help="save an event-study chart (light + dark PNG)")
    chart.add_argument("--type", default="shipping_attack", help="Event type id")
    chart.add_argument("--region", default="red_sea", help="Region id")
    chart.add_argument("--out", default="docs/charts/event-study.png")
    chart.set_defaults(func=cmd_chart)
    g = sub.add_parser("gdelt", help="ingest GDELT Candidates")
    g.add_argument("action", choices=["backfill", "pull", "stats"])
    g.add_argument("--start", default="2015-01-01")
    g.add_argument("--end", default=None, help="default: yesterday")
    g.add_argument("--workers", type=int, default=6)
    g.add_argument("--all", action="store_true", help="every Region and type, not just the first slice")
    g.set_defaults(func=cmd_gdelt)
    rf = sub.add_parser("refine", help="LLM-refine Candidates into Events")
    rf.add_argument("--fake", action="store_true", help="dry run with the deterministic refiner")
    rf.add_argument("--backfill", action="store_true", help="charge the one-time backfill budget")
    rf.add_argument("--per-day", type=int, default=3, help="most-covered URLs per day and type")
    rf.add_argument("--since", default=None, help="only Candidates on/after this ISO date")
    rf.add_argument("--limit", type=int, default=None)
    rf.set_defaults(func=cmd_refine)
    rc = sub.add_parser("recommend", help="Recommendations for the latest Episode starts")
    rc.add_argument("--latest", type=int, default=3)
    rc.add_argument("--fake", action="store_true", help="template rationale instead of Claude")
    rc.set_defaults(func=cmd_recommend)
    sub.add_parser("backtest", help="back-test Recommendations without look-ahead").set_defaults(
        func=cmd_backtest
    )
    ev = sub.add_parser("eval", help="the Eval set: sample items, then score a refiner")
    ev.add_argument("action", choices=["sample", "panel", "examples", "score", "progress"],
                    help="panel: label the Eval set with the Codex labeler/skeptic/judge panel")
    ev.add_argument("--n", type=int, default=100)
    ev.add_argument("--split", choices=["test", "teach"], default="test",
                    help="sample: 'teach' items supply worked examples and are never scored")
    ev.add_argument("--seed", type=int, default=7)
    ev.add_argument("--fake", action="store_true")
    ev.add_argument("--model", default=None,
                    help="score: refinement model to compare; panel: Codex model")
    ev.set_defaults(func=cmd_eval)
    jb = sub.add_parser("jobs", help="run a scheduled job once")
    jb.add_argument("which", choices=["hourly", "daily"])
    jb.set_defaults(func=cmd_jobs)
    sub.add_parser("scheduler", help="run the hourly/daily jobs forever").set_defaults(
        func=cmd_scheduler
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
