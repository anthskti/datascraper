"""
Orchestrator for YesStyle product scraping.

Input:  Brand,Name CSV or a brand,url product URL list
Output: outputs/runs/yesstyle_manual/products.csv
"""

import asyncio
import csv
import logging
from pathlib import Path
from urllib.parse import urlsplit

from datascraper.models import OUTPUT_FIELDS
from datascraper.taxonomy import normalize_product_identity_text
from datascraper.sources.v1.yesstyle.scraper import (
    get_first_product_link,
    scrape_yesstyle_product,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[5]
INPUT_CSV = _ROOT / "inputs" / "legacy" / "yesstyle_products.csv"
OUTPUT_CSV = _ROOT / "outputs" / "runs" / "yesstyle_manual" / "products.csv"
MAX_WORKERS = 5 # Conservative default for lower throttle risk on 100+ runs
DELAY_BETWEEN_REQUESTS = 5 # Seconds reduces throttle risk
MERCHANT = "Yesstyle"

def _product_key(brand: str, product_name: str) -> str:
    return f"{normalize_product_identity_text(brand)}::{normalize_product_identity_text(product_name)}"


def _read_input_products(input_csv: Path) -> list[dict[str, str]]:
    with input_csv.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Input CSV must have a header row")
        headers = {header.strip().casefold(): header for header in reader.fieldnames}
        brand_col = headers.get("brand")
        name_col = headers.get("name")
        url_col = headers.get("url")
        if not url_col and not (brand_col and name_col):
            raise ValueError("Input CSV needs a URL column or Brand,Name columns")

        products: list[dict[str, str]] = []
        for row in reader:
            products.append(
                {
                    "brand": (row.get(brand_col) or "").strip() if brand_col else "",
                    "product_name": (row.get(name_col) or "").strip() if name_col else "",
                    "url": (row.get(url_col) or "").strip() if url_col else "",
                }
            )
    products = [
        product
        for product in products
        if product["url"] or (product["brand"] and product["product_name"])
    ]
    for product in products:
        if not product["url"]:
            continue
        parts = urlsplit(product["url"])
        host = (parts.hostname or "").casefold()
        if (
            parts.scheme.casefold() not in {"http", "https"}
            or not (host == "yesstyle.com" or host.endswith(".yesstyle.com"))
            or "/info.html/pid." not in parts.path.casefold()
        ):
            raise ValueError(f"Not a YesStyle product URL: {product['url']}")
    return products

# ── Semaphore-limited scrape task ────
async def scrape_one(input_data: dict, semaphore: asyncio.Semaphore, delay_seconds: float) -> dict:
    async with semaphore:
        brand = input_data.get("brand", "")
        product_name = input_data.get("product_name", "")
        direct_url = input_data.get("url", "")
        search_query = f"{brand} {product_name}".strip()
        result = {
            "name":         product_name or "N/A",
            "brand":        brand or "N/A",
            "category":     "N/A",
            "labels":       "",
            "skinType":     "N/A",
            "skinTypeSource": "",
            "country":      "N/A",
            "capacity":     "N/A",
            "price":        "N/A",
            "instructions": "N/A",
            "ingredients":  "N/A",
            "imageUrls":    "N/A",
            "averageRating":"N/A",
            "url":          "N/A",
            "merchant":     MERCHANT,
            "status":       "failed"     # overwritten on success
        }

        try:
            logger.info(
                "Starting product scrape: target=%s",
                direct_url or search_query,
            )
            url = direct_url or await get_first_product_link(search_query)
            if not url:
                logger.warning("[%s] No product link found", search_query)
                return result
            
            result["url"] = url
            data = await scrape_yesstyle_product(url, product_name=product_name or None)
            scraped_brand = str(data.get("brand", "")).strip()
            scraped_name = str(data.get("name", "")).strip()
            if direct_url:
                if (
                    not scraped_brand
                    or scraped_brand == "N/A"
                    or not scraped_name
                    or scraped_name == "N/A"
                ):
                    logger.warning("[%s] Product page is missing its brand or name", url)
                    return result
                if brand and _product_key(brand, "") != _product_key(scraped_brand, ""):
                    logger.warning(
                        "[%s] Page brand %s did not match seed brand %s",
                        url,
                        scraped_brand,
                        brand,
                    )
                    return result
                result["brand"] = scraped_brand
                result["name"] = scraped_name

            result.update({
                "category":      data.get("category", "N/A"),
                "labels":        data.get("labels", ""),
                "skinType":      data.get("skinType", "N/A"),
                "skinTypeSource": "",
                "country":       data.get("country", "N/A"),
                "capacity":      data.get("capacity", "N/A"),
                "price":         data.get("price", "N/A"),
                "instructions":  data.get("how_to_use", "N/A"),
                "ingredients":   data.get("ingredients", "N/A"),
                "imageUrls":     "|".join(data.get("images", [])), # pipe-separated in CSV
                "averageRating": data.get("rating", "N/A"),
                "status":        "success"
            })
            logger.info(
                "Product scrape succeeded: name=%s brand=%s url=%s",
                result["name"],
                result["brand"],
                url,
            )

        except Exception as e:
            logger.exception("[%s] Scrape failed: %s", direct_url or search_query, e)
        finally:
            await asyncio.sleep(delay_seconds)
        return result
    
# ── Main pipeline ────────────────────
async def run_pipeline(
    input_csv: Path = INPUT_CSV,
    output_csv: Path = OUTPUT_CSV,
    max_workers: int = MAX_WORKERS,
    delay_between_requests: float = DELAY_BETWEEN_REQUESTS,
):
    if not input_csv.exists():
        logger.error(
            "Input file not found: %s. Use Brand,Name or a URL column",
            input_csv,
        )
        return

    try:
        products = _read_input_products(input_csv)
    except ValueError as exc:
        logger.error("Invalid input CSV: %s", exc)
        return

    logger.info("Loaded %d products from %s", len(products), input_csv)

    scraped = set() # Successful names or URLs are skipped on resume.
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        with open(output_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("status") != "success":
                    continue
                if row.get("url") and row.get("url") != "N/A":
                    scraped.add(f"url::{row['url'].strip().casefold()}")
                elif row.get("brand") and row.get("name"):
                    scraped.add(_product_key(row["brand"], row["name"]))
        logger.info("Resuming — %d already scraped, skipping them...", len(scraped))

    remaining = [
        p for p in products
        if (
            f"url::{p['url'].casefold()}" not in scraped
            if p["url"]
            else _product_key(p["brand"], p["product_name"]) not in scraped
        )
    ]
    logger.info("%d products left to scrape", len(remaining))
    if not remaining:
        logger.info("Nothing to scrape. Exiting.")
        return

    logger.info(
        "Starting YesStyle scrape with workers=%d delay_seconds=%.2f",
        max_workers,
        delay_between_requests,
    )

    # Concurrent Running Limit
    semaphore = asyncio.Semaphore(max_workers)
    tasks = [scrape_one(prod, semaphore, delay_between_requests) for prod in remaining]
    
    # Open CSV and append
    # Safety for crashing
    write_header = not output_csv.exists()
    with open(output_csv, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if write_header:
            writer.writeheader()

        completed = 0
        success_count = 0
        failed_count = 0
        for coro in asyncio.as_completed(tasks):
            row = await coro
            writer.writerow(row)
            f.flush()                   # write to disk immediately, don't buffer
            completed += 1
            if row["status"] == "success":
                success_count += 1
            else:
                failed_count += 1
            logger.info(
                "Progress: %d/%d — [%s] %s",
                completed, len(remaining),
                row["status"].upper(),
                row["name"]
            )

    logger.info(
        "Done. processed=%d succeeded=%d failed=%d output=%s",
        completed,
        success_count,
        failed_count,
        output_csv,
    )
