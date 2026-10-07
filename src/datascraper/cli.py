"""Command line entry point for datascraper."""

import argparse
import asyncio
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="datascraper")
    commands = parser.add_subparsers(dest="command", required=True)
    scrape = commands.add_parser("scrape", help="Scrape a merchant's product catalog")
    merchants = scrape.add_subparsers(dest="merchant", required=True)

    for name in ("yesstyle", "sephora"):
        merchant_parser = merchants.add_parser(name)
        merchant_parser.add_argument("--input", type=Path)
        merchant_parser.add_argument("--output", type=Path)
        merchant_parser.add_argument("--workers", type=int)
        merchant_parser.add_argument("--delay", type=float)

    args = parser.parse_args()
    if args.command == "scrape" and args.merchant == "yesstyle":
        from datascraper.sources.yesstyle.scrape import (
            DELAY_BETWEEN_REQUESTS,
            INPUT_CSV,
            MAX_WORKERS,
            OUTPUT_CSV,
            run_pipeline,
        )
    else:
        from datascraper.sources.sephora.scrape import (
            DELAY_BETWEEN_REQUESTS,
            INPUT_CSV,
            MAX_WORKERS,
            OUTPUT_CSV,
            run_pipeline,
        )

    asyncio.run(
        run_pipeline(
            input_csv=args.input or INPUT_CSV,
            output_csv=args.output or OUTPUT_CSV,
            max_workers=max(1, args.workers if args.workers is not None else MAX_WORKERS),
            delay_between_requests=max(
                0.0, args.delay if args.delay is not None else DELAY_BETWEEN_REQUESTS
            ),
        )
    )
