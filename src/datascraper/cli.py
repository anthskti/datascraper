"""Command line entry point for datascraper."""

import argparse
import asyncio
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)


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

    images = commands.add_parser("images", help="Ingest product images into R2")
    image_commands = images.add_subparsers(dest="image_command", required=True)
    ingest = image_commands.add_parser("ingest", help="Create an import CSV with R2 image URLs")
    ingest.add_argument("--input", type=Path, required=True)
    ingest.add_argument("--output", type=Path, required=True)
    ingest.add_argument("--progress", type=Path)
    ingest.add_argument("--dry-run", action="store_true")

    backfill = commands.add_parser("backfill", help="Backfill existing product data")
    backfill_commands = backfill.add_subparsers(dest="backfill_type", required=True)
    backfill_images = backfill_commands.add_parser("images", help="Ingest images from an existing CSV")
    repo_root = Path(__file__).resolve().parents[2]
    backfill_images.add_argument("--input", type=Path, default=repo_root / "outputs" / "master.csv")
    backfill_images.add_argument("--output", type=Path, default=repo_root / "outputs" / "master_r2.csv")
    backfill_images.add_argument("--progress", type=Path)
    backfill_images.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "images" or args.command == "backfill":
        from datascraper.pipeline.images import ingest_images

        try:
            ingest_images(
                input_csv=args.input,
                output_csv=args.output,
                dry_run=args.dry_run,
                progress_path=getattr(args, "progress", None),
            )
        except Exception as exc:
            parser.exit(1, f"datascraper: error: {exc}\n")
        return

    if args.merchant == "yesstyle":
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
