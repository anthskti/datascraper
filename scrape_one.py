import asyncio
import argparse
import csv
import logging
from pathlib import Path
from yesstyle_scrapper import get_first_product_link, scrape_yesstyle_product

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────
INPUT_CSV = "product_input.csv"
OUTPUT_CSV = "product_output.csv"
MAX_WORKERS = 5 # Conservative default for lower throttle risk on 100+ runs
DELAY_BETWEEN_REQUESTS = 5 # Seconds reduces throttle risk

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
    "status"
]

def _product_key(brand: str, product_name: str) -> str:
    return f"{brand.strip().lower()}::{product_name.strip().lower()}"

# ── Semaphore-limited scrape task ────
async def scrape_one(input_data: dict, semaphore: asyncio.Semaphore, delay_seconds: float) -> dict:
    async with semaphore:
        brand = input_data["brand"]
        product_name = input_data["product_name"]
        search_query = f"{brand} {product_name}"
        result = {
            "name":         product_name,
            "brand":        brand,
            "category":     "N/A",
            "labels":       "",
            "skinType":     "N/A",
            "country":      "N/A",
            "capacity":     "N/A",
            "price":        "N/A",
            "instructions": "N/A",
            "ingredients":  "N/A",
            "imageUrls":    "N/A",
            "averageRating":"N/A",
            "url":          "N/A",
            "status":       "failed"     # overwritten on success
        }

        try:
            url = await get_first_product_link(search_query)
            if not url:
                logger.warning("[%s] No product link found", search_query)
                return result
            
            result["url"] = url
            data = await scrape_yesstyle_product(url, product_name=product_name)

            result.update({
                "category":      data.get("category", "N/A"),
                "labels":        data.get("labels", ""),
                "skinType":      data.get("skinType", "N/A"),
                "country":       data.get("country", "N/A"),
                "capacity":      data.get("capacity", "N/A"),
                "price":         data.get("price", "N/A"),
                "instructions":  data.get("how_to_use", "N/A"),
                "ingredients":   data.get("ingredients", "N/A"),
                "imageUrls":     "|".join(data.get("images", [])), # pipe-separated in CSV
                "averageRating": data.get("rating", "N/A"),
                "status":        "success"
            })

        except Exception as e:
            logger.error("[%s] Scrape failed: %s", product_name, e)
        
        await asyncio.sleep(delay_seconds)
        return result
    
# ── Main pipeline ────────────────────
async def run_pipeline(
    input_csv: str = INPUT_CSV,
    output_csv: str = OUTPUT_CSV,
    max_workers: int = MAX_WORKERS,
    delay_between_requests: float = DELAY_BETWEEN_REQUESTS,
):
    input_path = Path(input_csv)
    if not input_path.exists():
        logger.error(
            "Input file not found: %s. Create it with columns: Brand,Name",
            input_csv,
        )
        return

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        products = [
            {
                "brand": row["Brand"].strip(), 
                "product_name": row["Name"].strip()
            } 
            for row in reader
        ]

    logger.info("Loaded %d products from %s", len(products), input_csv)

    scraped = set() # Used so it doesn't double scrape successful rows
    output_path = Path(output_csv)
    if output_path.exists():
        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            scraped = {
                _product_key(row.get("brand", ""), row.get("name", ""))
                for row in reader
                if row.get("status") == "success" and row.get("brand") and row.get("name")
            }
        logger.info("Resuming — %d already scraped, skipping them...", len(scraped))

    remaining = [
        p for p in products
        if _product_key(p["brand"], p["product_name"]) not in scraped
    ]
    logger.info("%d products left to scrape", len(remaining))
    if not remaining:
        logger.info("Nothing to scrape. Exiting.")
        return

    # Concurrent Running Limit
    semaphore = asyncio.Semaphore(max_workers)
    tasks = [scrape_one(prod, semaphore, delay_between_requests) for prod in remaining]
    
    # Open CSV and append
    # Safety for crashing
    write_header = not output_path.exists()
    with open(output_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if write_header:
            writer.writeheader()

        completed = 0
        for coro in asyncio.as_completed(tasks):
            row = await coro
            writer.writerow(row)
            f.flush()                   # write to disk immediately, don't buffer
            completed += 1
            logger.info(
                "Progress: %d/%d — [%s] %s",
                completed, len(remaining),
                row["status"].upper(),
                row["name"]
            )

    logger.info("Done. Output saved to %s", output_csv)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape YesStyle product data from an input CSV."
    )
    parser.add_argument(
        "--input",
        default=INPUT_CSV,
        help="Input CSV path (default: product_input.csv)",
    )
    parser.add_argument(
        "--output",
        default=OUTPUT_CSV,
        help="Output CSV path (default: product_output.csv)",
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
        help=f"Delay in seconds per task after each scrape (default: {DELAY_BETWEEN_REQUESTS})",
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