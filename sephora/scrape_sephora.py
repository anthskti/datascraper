"""
Orchestrator for Sephora product scraping.

Input:  inputs/sephora_input.csv          (product_id, url)
Output: outputs/sephora_output.csv        (schema matches sephora_expected_output.csv)
"""

import argparse
import asyncio
import csv
import logging
import re
from pathlib import Path

from sephora_scrapper import scrape_sephora_product

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
INPUT_CSV = _ROOT / "inputs" / "sephora_input.csv"
OUTPUT_CSV = _ROOT / "outputs" / "sephora_output.csv"
MAX_WORKERS = 2
DELAY_BETWEEN_REQUESTS = 8
MERCHANT = "Sephora"

OUTPUT_FIELDS = [
    "name",
    "brand",
    "category",
    "labels",
    "skinType",
    "country",
    "capacity",
    "price",
    "instructions",
    "ingredients",
    "imageUrls",
    "averageRating",
    "url",
    "merchant",
    "status",
]

_PRODUCT_ID_RE = re.compile(r"-P(\d+)$", re.IGNORECASE)


def _product_id_from_url(url: str) -> str | None:
    match = _PRODUCT_ID_RE.search(url.strip())
    return f"P{match.group(1)}" if match else None


def _failed_row(url: str, status: str = "failed") -> dict:
    return {
        "name": "N/A",
        "brand": "N/A",
        "category": "N/A",
        "labels": "",
        "skinType": "N/A",
        "country": "N/A",
        "capacity": "N/A",
        "price": "N/A",
        "instructions": "N/A",
        "ingredients": "N/A",
        "imageUrls": "N/A",
        "averageRating": "N/A",
        "url": url,
        "merchant": MERCHANT,
        "status": status,
    }


def _to_output_row(data: dict, url: str) -> dict:
    images = data.get("imageUrls", [])
    if isinstance(images, list):
        image_urls = "|".join(images) if images else "N/A"
    else:
        image_urls = images or "N/A"

    return {
        "name": data.get("name", "N/A"),
        "brand": data.get("brand", "N/A"),
        "category": data.get("category", "N/A"),
        "labels": data.get("labels", ""),
        "skinType": data.get("skinType", "N/A"),
        "country": data.get("country", "N/A"),
        "capacity": data.get("capacity", "N/A"),
        "price": data.get("price", "N/A"),
        "instructions": data.get("instructions", "N/A"),
        "ingredients": data.get("ingredients", "N/A"),
        "imageUrls": image_urls,
        "averageRating": data.get("rating", "N/A"),
        "url": url,
        "merchant": MERCHANT,
        "status": data.get("status", "failed"),
    }


async def scrape_one_product(
    row: dict,
    semaphore: asyncio.Semaphore,
    delay_seconds: float,
) -> dict:
    url = row["url"].strip()
    product_id = row.get("product_id", "").strip() or _product_id_from_url(url) or ""

    async with semaphore:
        result = _failed_row(url)
        try:
            data = await scrape_sephora_product(url, product_id)
            result = _to_output_row(data, url)
        except Exception as exc:
            logger.error("[%s] Scrape failed: %s", url, exc)

        await asyncio.sleep(delay_seconds)
        return result


async def run_pipeline(
    input_csv: Path = INPUT_CSV,
    output_csv: Path = OUTPUT_CSV,
    max_workers: int = MAX_WORKERS,
    delay_between_requests: float = DELAY_BETWEEN_REQUESTS,
) -> None:
    if not input_csv.exists():
        logger.error(
            "Input file not found: %s. Create it with columns: product_id,url",
            input_csv,
        )
        return

    with open(input_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        products = [
            {
                "product_id": row["product_id"].strip(),
                "url": row["url"].strip(),
            }
            for row in reader
            if row.get("url", "").strip()
        ]

    logger.info("Loaded %d products from %s", len(products), input_csv)

    scraped_urls: set[str] = set()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        with open(output_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            scraped_urls = {
                row["url"].strip()
                for row in reader
                if row.get("status") == "success" and row.get("url", "").strip()
            }
        logger.info("Resuming — %d already scraped, skipping them...", len(scraped_urls))

    remaining = [p for p in products if p["url"] not in scraped_urls]
    logger.info("%d products left to scrape", len(remaining))
    if not remaining:
        logger.info("Nothing to scrape. Exiting.")
        return

    semaphore = asyncio.Semaphore(max_workers)
    tasks = [
        scrape_one_product(row, semaphore, delay_between_requests)
        for row in remaining
    ]

    write_header = not output_csv.exists()
    with open(output_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if write_header:
            writer.writeheader()

        completed = 0
        for coro in asyncio.as_completed(tasks):
            row = await coro
            writer.writerow(row)
            f.flush()
            completed += 1
            logger.info(
                "Progress: %d/%d — [%s] %s",
                completed,
                len(remaining),
                row["status"].upper(),
                row["name"],
            )

    logger.info("Done. Output saved to %s", output_csv)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Sephora product data from an input CSV."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_CSV,
        help=f"Input CSV path (default: {INPUT_CSV})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_CSV,
        help=f"Output CSV path (default: {OUTPUT_CSV})",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Number of concurrent workers (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=DELAY_BETWEEN_REQUESTS,
        help=(
            f"Delay in seconds per task after each scrape "
            f"(default: {DELAY_BETWEEN_REQUESTS})"
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    workers = max(1, args.workers)
    delay = max(0.0, args.delay)
    asyncio.run(
        run_pipeline(
            input_csv=args.input,
            output_csv=args.output,
            max_workers=workers,
            delay_between_requests=delay,
        )
    )
