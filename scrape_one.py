import asyncio
import csv
import logging
from pathlib import Path
from yesstyle_scrapper import get_first_product_link, scrape_yesstyle_product

logger = logging.getLogger(__name__)

# ── Config ──────────────────────────
INPUT_CSV = "product_input.csv"
OUTPUT_CSV = "product_output.csv"
MAX_WORKERS = 10 # Concurrent Scrapers
DELAY_BETWEEN_REQUESTS = 5 # Seconds reduces throttle risk

OUTPUT_FIELDS = [
    "name", # From CSV
    "brand", # From CSV
    "category", # Yesstyle_scrapper, breadcrumbs
    # "skinType",
    # "country", # TODO
    # "capacity", # Need to scrap
    "price", 
    "instructions", # how_to_use 
    # "activeIngredient", # Weird
    "ingredients", 
    "imageUrls", 
    "averageRating",
    # "reviewCount", # don't add for now.
    "url", # the get_first_product_link
    "status"
]
# ── Semaphore-limited scrape task ────
async def scrape_one(input_data: dict, semaphore: asyncio.Semaphore) -> dict:
    async with semaphore:
        brand = input_data["brand"]
        product_name = input_data["product_name"]
        search_query = f"{brand} {product_name}"
        result = {
            "product_name": product_name,
            "brand":        brand,
            "price":        "N/A",
            "rating":       "N/A",
            "images":       "N/A",
            "how_to_use":   "N/A",
            "ingredients":  "N/A",
            "url":          "N/A",
            "status":       "failed"     # overwritten on success
        }

        try:
            url = await get_first_product_link(search_query)
            if not url:
                logger.warning("[%s] No product link found", search_query)
                return result
            
            result["url"] = url
            data = await scrape_yesstyle_product(url)

            result.update({
                "title":       data.get("title", "N/A"),
                "price":       data.get("price", "N/A"),
                "rating":      data.get("rating", "N/A"),
                "images":      "|".join(data.get("images", [])), # pipe-separated in CSV
                "how_to_use":  data.get("how_to_use", "N/A"),
                "ingredients": data.get("ingredients", "N/A"),
                "status":      "success"
            })

        except Exception as e:
            logger.error("[%s] Scrape failed: %s", product_name, e)
        
        await asyncio.sleep(DELAY_BETWEEN_REQUESTS)
        return result
    
# ── Main pipeline ────────────────────
async def run_pipeline():
    input_path = Path(INPUT_CSV)
    

    with open(input_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        products = [
            {
                "brand": row["brand"].strip(), 
                "product_name": row["product_name"].strip()
            } 
            for row in reader
        ]

    logger.info("Loaded %d products from %s", len(products), INPUT_CSV)

    scraped = set() # Used so it doesn't double scrap
    output_path = Path(OUTPUT_CSV)
    if output_path.exists():
        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            scraped = {row["product_name"] for row in reader}
        logger.info("Resuming — %d already scraped, skipping them...", len(scraped))

    remaining = [p for p in products if p not in scraped]
    logger.info("%d products left to scrape", len(remaining))

    # Concurrent Running Limit
    semaphore = asyncio.Semaphore(MAX_WORKERS)
    tasks = [scrape_one(prod, semaphore) for prod in remaining]
    
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
                row["product_name"]
            )

    logger.info("Done. Output saved to %s", OUTPUT_CSV)