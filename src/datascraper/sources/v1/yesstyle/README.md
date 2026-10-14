# YesStyle scraper (v1)

The YesStyle source extracts product data from merchant pages. Run the batch scraper from the repository root:

```bash
uv run datascraper scrape yesstyle --input inputs/legacy/yesstyle_products.csv --output outputs/runs/yesstyle_manual/products.csv --workers 5 --delay 5
```

This full discovery source package contains `extractors.py` (DOM extraction), `scraper.py` (single-product browser flow), and `scrape.py` (CSV batch orchestration). YesStyle currently extracts one image per product. Price-only refresh uses the separate [v2 source](../../v2/yesstyle/README.md).

## Brand URL discovery

Prepare a CSV with `brand,listingUrl` columns. Apify discovery and the local Playwright scraper remain separate commands so you can inspect the discovered URLs before scraping:

```bash
uv run datascraper discover yesstyle --input inputs/yesstyle/brand_pages.csv --output outputs/runs/yesstyle_skin1004/product_urls.csv --max-pages 300 --max-depth 3
uv run datascraper scrape yesstyle --input outputs/runs/yesstyle_skin1004/product_urls.csv --output outputs/runs/yesstyle_skin1004/products.csv --workers 2 --delay 5
uv run datascraper compare catalog --input outputs/runs/yesstyle_skin1004/products.csv --catalog outputs/catalog/master.csv --output-prefix outputs/runs/yesstyle_skin1004/comparison
```

`--max-pages` applies per brand and counts both listing and product pages. Set `APIFY_TOKEN` in the shell. Compact Apify manifests are saved beside the URL CSV under `apify/`; full page content stays in Apify. Pass `--dataset-id` to replay a dataset for a single brand seed. Inspect the URL CSV before scraping.

The comparison writes new products in the standard Clearup CSV schema. Existing and uncertain matches go to separate CSVs with a reason and candidate details. Clearup matching uses brand and name, so inspect capacity differences and uncertain names before import.
