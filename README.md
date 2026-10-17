# Product Data Scraper for Clearup

Quick command reference: [CHEATSHEET.md](CHEATSHEET.md).

This repository is a compliment to [Clearup.skin](https://www.clearup.skin)([repo](https://github.com/anthskti/Clearup)).

Currently focuses on these retail stores:

1. [YesStyle v1](src/datascraper/sources/v1/yesstyle/README.md) — full discovery scraper; drawback: skin types are inconsistent.
2. [Sephora v1](src/datascraper/sources/v1/sephora/README.md) — full discovery scraper; drawback: doesn't state country.
3. [YesStyle v2](src/datascraper/sources/v2/yesstyle/README.md) and [Sephora v2](src/datascraper/sources/v2/sephora/README.md) — price-only refresh scrapers.

General Pipeline:

1. Playwright: handles interaction and navigation throughout website.
2. Beautiful Soup: handles getting the data.

Generally gets this product information line:
name,brand,category,labels,skinType,country,capacity,price,instructions,ingredients,imageUrls,averageRating,url,merchant,status,skinTypeSource

## Setup

Need python and uv (package manager) installed.

```bash
uv sync
```

Scrape a merchant from an input CSV:

```bash
uv run datascraper scrape yesstyle --input inputs/legacy/yesstyle_products.csv --output outputs/runs/yesstyle_manual/products.csv --workers 5 --delay 5
uv run datascraper scrape sephora --input inputs/legacy/sephora_products_v2.csv --output outputs/runs/sephora_manual/products.csv --workers 4 --delay 8
```

Use `uv run datascraper --help` or `uv run datascraper scrape --help` for options. `datascraper scrape` uses the full v1 sources; `datascraper refresh prices` uses the price-only v2 sources. The discovery output schema is in `datascraper.models`.

## Discover YesStyle products from brand pages

Create a seed CSV with `brand,listingUrl` columns. The bounded Apify crawl writes a separate `brand,url` CSV; inspect it before passing it to the local Playwright scraper. `--max-pages` applies to each brand URL. Set `APIFY_TOKEN` in the shell; the CLI does not load `.env` automatically. Compact run manifests are saved beside the URL CSV under `apify/`, with dataset IDs for replay. Full page content remains in Apify.

```bash
uv run datascraper discover yesstyle --input inputs/yesstyle/brand_pages.csv --output outputs/runs/yesstyle_skin1004/product_urls.csv --max-pages 300 --max-depth 3
uv run datascraper scrape yesstyle --input outputs/runs/yesstyle_skin1004/product_urls.csv --output outputs/runs/yesstyle_skin1004/products.csv --workers 2 --delay 5
uv run datascraper compare catalog --input outputs/runs/yesstyle_skin1004/products.csv --catalog outputs/catalog/master.csv --output-prefix outputs/runs/yesstyle_skin1004/comparison
```

Both YesStyle commands write terminal logs and append to `run.log` beside their output. `INFO` is the default; add `--log-level DEBUG` to either command for per-page and URL filtering details. The product scrape logs navigation status and whether key fields were found, without logging ingredients or full page content.

The URL CSV is a visible checkpoint: inspect or edit it before scraping, and rerun the scraper independently. The crawl limit includes listing and product pages, so check the discovered/scraped row count against the brand listing. The comparison writes `_new.csv`, `_existing.csv`, and `_review.csv`; only `_new.csv` has the normal Clearup product import fields. Review the other two before importing, and make sure `outputs/catalog/master.csv` is current.

## Enrich product skin types locally

Install and start Ollama, then download the default model once:

```bash
ollama pull gemma4:12b-mlx
```

The local model infers skin types from the product name, category, and ingredients. Override the default with `--model` if needed. The input file is never modified, so compare the output against the original regex-based `skinType` values:

```bash
uv run datascraper enrich skin-types --input outputs/catalog/master.csv --output outputs/catalog/master_skin_types_sample.csv --limit 5
uv run datascraper enrich skin-types --input outputs/catalog/master.csv --output outputs/catalog/master_skin_types.csv
```

Inference is restricted to `ALL_SKIN_TYPES`; insufficient evidence produces `N/A`. The model considers the overall product purpose and formula, does not infer suitability from a single ingredient or marketing phrase, and should omit uncertain skin types. Product name, category, and ingredients are sent as structured data; the model is instructed to return only a JSON label array. The result is validated locally against the allowed taxonomy. Rows marked `skinTypeSource=manual` or `inferred` are skipped on reruns. Legacy rows without provenance are inferred once, even when they already contain a scraped skin type. The output adds the internal `skinTypeSource` field; Clearup must retain that field for manual edits and rerun-skipping to work end to end. This repository does not write to Clearup.

For later runs, use the latest enriched/import-export CSV as `--input`; reusing the original source CSV (without `skinTypeSource`) will intentionally trigger inference again. Keep the original CSV separately to compare model results with the regex values.

## Refresh merchant prices

The refresh command reads merchant listings from Clearup using a dedicated read-only PostgreSQL role, then writes successful price results to a separate four-column CSV. It does not update Clearup:

```bash
export CLEARUP_DATABASE_URL='postgresql://...session-pooler-connection...'
export CLEARUP_DB_CA_CERT='/path/to/supabase-prod-ca.crt'
uv run datascraper refresh prices --limit 5 --output outputs/refresh/price_refresh.csv
```

Use the exact session-pooler connection details from Supabase and a role limited to `SELECT` on `products`, `product_merchants`, and `merchants`. The connection verifies TLS and the server certificate/hostname using the configured CA. If `.env` is used, source it in the shell before running the command. The CSV columns are `brand,name,price,merchant`; failed, unsupported, and duplicate brand/name/merchant listings are omitted and counted in the log, so a failed scrape cannot replace a stored price. YesStyle and Sephora are currently supported; Sephora may block automated requests.

## Product images

Create an R2 bucket separately in Cloudflare, enable public access through a custom domain, and create an access key with permission for that bucket. Set `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, and `R2_PUBLIC_BASE_URL` in the shell environment before uploading. A local `.env` must be sourced by the shell; the CLI does not load it automatically.

Convert a scraper CSV into an import CSV containing R2 URLs:

```bash
uv run datascraper images ingest --input outputs/runs/yesstyle_skin1004/products.csv --output outputs/runs/yesstyle_skin1004/image_import.csv --dry-run
uv run datascraper images ingest --input outputs/runs/yesstyle_skin1004/products.csv --output outputs/runs/yesstyle_skin1004/image_import.csv
```

The dry run lists planned object keys without downloading or uploading images and does not write the output CSV.

Backfill the merged dataset (resumable; progress is stored under ignored `outputs/`):

```bash
uv run datascraper backfill images --input outputs/catalog/master.csv --output outputs/catalog/master_r2.csv --dry-run
uv run datascraper backfill images --input outputs/catalog/master.csv --output outputs/catalog/master_r2.csv
```

R2 product keys use a SHA-256 digest of the trimmed, lowercased `brand::name` identity, followed by the image position and source-URL digest. Scraper CSVs retain their original merchant image URLs; the derived import CSV contains R2 URLs and only includes successful rows with images. Unsuccessful and imageless rows are skipped so they cannot clear existing images. Ingest continues through the batch after an image error and logs `processed`, `skipped`, and `failed` row counts; if any eligible row fails, it does not write a new output CSV. Completed uploads are resumable on rerun.

Author: Anthony Pham
Created: February 17, 2026
Last Updated: October 7, 2026
