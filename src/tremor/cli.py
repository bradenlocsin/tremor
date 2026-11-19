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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tremor", description="Tracking Risk Events & Market Outcome Reactions"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="show the loaded configuration").set_defaults(func=cmd_info)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
