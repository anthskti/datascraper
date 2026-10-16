"""Command line entry point for datascraper."""

import argparse
import asyncio
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)


def _configure_run_logging(log_path: Path, log_level: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))

    resolved_path = str(log_path.resolve())
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and handler.baseFilename == resolved_path:
            handler.setLevel(getattr(logging, log_level.upper()))
            return

    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setLevel(getattr(logging, log_level.upper()))
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root_logger.addHandler(file_handler)


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
        if name == "yesstyle":
            merchant_parser.add_argument(
                "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
            )

    discover = commands.add_parser("discover", help="Discover product URLs from retailer listings")
    discover_commands = discover.add_subparsers(dest="discover_source", required=True)
    yesstyle_discover = discover_commands.add_parser(
        "yesstyle", help="Discover YesStyle product URLs from brand listing pages"
    )
    yesstyle_discover.add_argument("--input", type=Path, required=True)
    yesstyle_discover.add_argument("--output", type=Path, required=True, help="brand,url CSV")
    yesstyle_discover.add_argument("--max-pages", type=int, default=30)
    yesstyle_discover.add_argument("--max-depth", type=int, default=3)
    yesstyle_discover.add_argument("--dataset-id", help="Reuse a saved Apify dataset (one brand row only)")
    yesstyle_discover.add_argument("--wait-timeout", type=float, default=3600)
    yesstyle_discover.add_argument(
        "--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO"
    )

    compare = commands.add_parser("compare", help="Compare scraped products with a catalog CSV")
    compare_commands = compare.add_subparsers(dest="compare_type", required=True)
    catalog = compare_commands.add_parser("catalog", help="Split products into new, existing, and review CSVs")
    catalog.add_argument("--input", type=Path, required=True)
    catalog.add_argument("--catalog", type=Path, required=True)
    catalog.add_argument("--output-prefix", type=Path, required=True)

    refresh = commands.add_parser("refresh", help="Refresh prices for Clearup merchant listings")
    refresh_commands = refresh.add_subparsers(dest="refresh_type", required=True)
    prices = refresh_commands.add_parser("prices", help="Write refreshed merchant prices to CSV")
    prices.add_argument("--output", type=Path, default=Path("outputs/refresh/price_refresh.csv"))
    prices.add_argument("--limit", type=int, help="Refresh at most this many Clearup listings")
    prices.add_argument("--workers", type=int, default=1)
    prices.add_argument("--delay", type=float, default=5.0)

    enrich = commands.add_parser("enrich", help="Enrich product CSV data locally")
    enrich_commands = enrich.add_subparsers(dest="enrich_type", required=True)
    skin_types = enrich_commands.add_parser(
        "skin-types", help="Infer product skin types with a local Ollama model"
    )
    skin_types.add_argument("--input", type=Path, required=True)
    skin_types.add_argument("--output", type=Path, required=True)
    skin_types.add_argument("--limit", type=int, help="Process at most this many eligible rows")
    skin_types.add_argument("--model", default="gemma4:12b-mlx")
    skin_types.add_argument("--ollama-url", default="http://localhost:11434")

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
    backfill_images.add_argument(
        "--input", type=Path, default=repo_root / "outputs" / "catalog" / "master.csv"
    )
    backfill_images.add_argument(
        "--output", type=Path, default=repo_root / "outputs" / "catalog" / "master_r2.csv"
    )
    backfill_images.add_argument("--progress", type=Path)
    backfill_images.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    if args.command == "discover":
        from datascraper.sources.v1.yesstyle.discover import discover_yesstyle_urls

        try:
            _configure_run_logging(args.output.parent / "run.log", args.log_level)
            logging.getLogger(__name__).info(
                "Starting YesStyle URL discovery: input=%s output=%s",
                args.input,
                args.output,
            )
            discover_yesstyle_urls(
                input_csv=args.input,
                output_csv=args.output,
                max_pages=args.max_pages,
                max_depth=args.max_depth,
                dataset_id=args.dataset_id,
                wait_timeout=args.wait_timeout,
                artifact_dir=args.output.parent / "apify",
            )
        except Exception as exc:
            logging.getLogger(__name__).exception("YesStyle URL discovery failed")
            parser.exit(1, f"datascraper: error: {exc}\n")
        return

    if args.command == "compare":
        from datascraper.pipeline.discovery import compare_with_catalog

        try:
            compare_with_catalog(
                input_csv=args.input,
                catalog_csv=args.catalog,
                output_prefix=args.output_prefix,
            )
        except Exception as exc:
            parser.exit(1, f"datascraper: error: {exc}\n")
        return

    if args.command == "refresh":
        from datascraper.pipeline.refresh import refresh_prices

        try:
            asyncio.run(
                refresh_prices(
                    output_csv=args.output,
                    limit=args.limit,
                    max_workers=max(1, args.workers),
                    delay_between_requests=max(0.0, args.delay),
                )
            )
        except Exception as exc:
            parser.exit(1, f"datascraper: error: {exc}\n")
        return

    if args.command == "enrich":
        from datascraper.pipeline.enrichment import enrich_skin_types

        try:
            enrich_skin_types(
                input_csv=args.input,
                output_csv=args.output,
                limit=args.limit,
                model=args.model,
                ollama_url=args.ollama_url,
            )
        except Exception as exc:
            parser.exit(1, f"datascraper: error: {exc}\n")
        return

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
        from datascraper.sources.v1.yesstyle.scrape import (
            DELAY_BETWEEN_REQUESTS,
            INPUT_CSV,
            MAX_WORKERS,
            OUTPUT_CSV,
            run_pipeline,
        )
    else:
        from datascraper.sources.v1.sephora.scrape import (
            DELAY_BETWEEN_REQUESTS,
            INPUT_CSV,
            MAX_WORKERS,
            OUTPUT_CSV,
            run_pipeline,
        )

    if args.merchant == "yesstyle":
        output_path = args.output or OUTPUT_CSV
        _configure_run_logging(output_path.parent / "run.log", args.log_level)
        logging.getLogger(__name__).info(
            "Starting YesStyle product scrape: input=%s output=%s",
            args.input or INPUT_CSV,
            output_path,
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
