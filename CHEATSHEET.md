# Datascraper CLI Cheat Sheet

Quick reference for the YesStyle product pipeline. Run commands from the repository root.

## YesStyle brand listing → reviewed products

### 1. Discover product URLs

Prepare `inputs/yesstyle/brand_pages.csv` with `brand,listingUrl` columns, then run:

```bash
uv run datascraper discover yesstyle \
  --input inputs/yesstyle/brand_pages.csv \
  --output outputs/runs/yesstyle_skin1004/product_urls.csv \
  --max-pages 300 --max-depth 3
```

\*Note: adjust max-pages depending on products. max-page 20 approximately grabs 17 products and it's around 8 cents.

Set `APIFY_TOKEN` in your shell first. For a small trial, lower `--max-pages` (for example, `1`). Discovery saves product URLs to a CSV and Apify run details under the sibling `apify/` folder. Inspect the URL CSV before scraping.

### 2. Scrape the product pages

```bash
uv run datascraper scrape yesstyle \
  --input outputs/runs/yesstyle_skin1004/product_urls.csv \
  --output outputs/runs/yesstyle_skin1004/products.csv \
  --workers 2 --delay 5
```

This writes product data in the Clearup CSV format. Both discovery and scraping write a `run.log` beside their output. Use `--log-level DEBUG` for more detail.

### 3. Compare with the current master catalog

```bash
uv run datascraper compare catalog \
  --input outputs/runs/yesstyle_skin1004/products.csv \
  --catalog outputs/catalog/master.csv \
  --output-prefix outputs/runs/yesstyle_skin1004/comparison
```

This creates three files:

- `comparison_new.csv`: no likely catalog match; review these as candidates to add.
- `comparison_existing.csv`: same listing URL, or same brand, name, and capacity; likely already represented in the catalog.
- `comparison_review.csv`: a possible match needs a human decision. For example, a 30 ml Mini may match a regular or Jumbo listing by name but differ in capacity.

The existing and review files show the scraped product fields first, followed by `reviewReason` and the matched catalog fields (`matchedName`, `matchedBrand`, `matchedCapacity`, `matchedUrl`). This is a classification report, not a side-by-side field diff. Clean and resolve the results before adding accepted products to the master; do not append the entire scrape blindly.

## Other useful commands

Infer skin types for a small sample (requires Ollama running locally):

```bash
uv run datascraper enrich skin-types \
  --input outputs/runs/yesstyle_skin1004/comparison_new.csv \
  --output outputs/runs/yesstyle_skin1004/products_enriched.csv \
  --limit 5
```

See available commands and options:

```bash
uv run datascraper --help
uv run datascraper discover yesstyle --help
uv run datascraper scrape yesstyle --help
uv run datascraper compare catalog --help
```
