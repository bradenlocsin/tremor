"""Command-line entry point: `tremor <command>`."""

from __future__ import annotations

import argparse
import sys

from tremor.config import load_config


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
    from tremor.event_study import study
    from tremor.events import load_events
    from tremor.prices import load_prices
    from tremor.storage import connect
    from tremor.taxonomy import default_taxonomy

    cfg = load_config()
    tax = default_taxonomy()
    conn = connect(cfg.storage_path)
    prices = load_prices(conn, cfg.tickers)
    events = load_events(conn, event_type=args.type, region=args.region)
    results = [
        study(prices, events, a.ticker, cfg.benchmark, cfg.event_study) for a in cfg.assets
    ]
    title = f"{tax.event_type(args.type).name}s, {tax.region(args.region).name}: average CAR"
    names = {a.ticker: a.category for a in cfg.assets}
    out = Path(args.out)
    for theme in ("light", "dark"):
        path = out.with_name(f"{out.stem}-{theme}{out.suffix}")
        save(plot_study(results, title, names, theme), path)
        print(f"wrote {path}")
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
