# Product Data Scraper for Clearup

This repository is a compliment to [Clearup.skin](https://www.clearup.skin)([repo](https://github.com/anthskti/Clearup)).

Currently focuses on these retail stores:

1. [YesStyle v1](src/datascraper/sources/v1/yesstyle/README.md) — full discovery scraper; drawback: skin types are inconsistent.
2. [Sephora v1](src/datascraper/sources/v1/sephora/README.md) — full discovery scraper; drawback: doesn't state country.
3. [YesStyle v2](src/datascraper/sources/v2/yesstyle/README.md) and [Sephora v2](src/datascraper/sources/v2/sephora/README.md) — price-only refresh scrapers.

General Pipeline:

1. Playwright: handles interaction and navigation throughout website.
2. Beautiful Soup: handles getting the data.

Generally gets this product information line:
name,brand,category,labels,skinType,country,capacity,price,instructions,ingredients,imageUrls,averageRating,url,merchant,status

## Setup

Need python and uv (package manager) installed.

```bash
uv sync
```

Scrape a merchant from an input CSV:

```bash
uv run datascraper scrape yesstyle --input inputs/yesstyle_input_v2.csv --output outputs/yesstyle_output.csv --workers 5 --delay 5
uv run datascraper scrape sephora --input inputs/sephora_input.csv --output outputs/sephora_output.csv --workers 4 --delay 8
```

Use `uv run datascraper --help` or `uv run datascraper scrape --help` for options. `datascraper scrape` uses the full v1 sources; `datascraper refresh prices` uses the price-only v2 sources. The discovery output schema is in `datascraper.models`.

## Refresh merchant prices

The refresh command reads merchant listings from Clearup using a dedicated read-only PostgreSQL role, then writes successful price results to a separate four-column CSV. It does not update Clearup:

```bash
export CLEARUP_DATABASE_URL='postgresql://...session-pooler-connection...'
export CLEARUP_DB_CA_CERT='/path/to/supabase-prod-ca.crt'
uv run datascraper refresh prices --limit 5 --output outputs/price_refresh.csv
```

Use the exact session-pooler connection details from Supabase and a role limited to `SELECT` on `products`, `product_merchants`, and `merchants`. The connection verifies TLS and the server certificate/hostname using the configured CA. If `.env` is used, source it in the shell before running the command. The CSV columns are `brand,name,price,merchant`; failed, unsupported, and duplicate brand/name/merchant listings are omitted and counted in the log, so a failed scrape cannot replace a stored price. YesStyle and Sephora are currently supported; Sephora may block automated requests.

## Product images

Create an R2 bucket separately in Cloudflare, enable public access through a custom domain, and create an access key with permission for that bucket. Set `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, and `R2_PUBLIC_BASE_URL` in the shell environment before uploading. A local `.env` must be sourced by the shell; the CLI does not load it automatically.

Convert a scraper CSV into an import CSV containing R2 URLs:

```bash
uv run datascraper images ingest --input outputs/yesstyle_output.csv --output outputs/yesstyle_import.csv --dry-run
uv run datascraper images ingest --input outputs/yesstyle_output.csv --output outputs/yesstyle_import.csv
```

The dry run lists planned object keys without downloading or uploading images and does not write the output CSV.

Backfill the merged dataset (resumable; progress is stored under ignored `outputs/`):

```bash
uv run datascraper backfill images --input outputs/master.csv --output outputs/master_r2.csv --dry-run
uv run datascraper backfill images --input outputs/master.csv --output outputs/master_r2.csv
```

R2 product keys use a SHA-256 digest of the trimmed, lowercased `brand::name` identity, followed by the image position and source-URL digest. Scraper CSVs retain their original merchant image URLs; the derived import CSV contains R2 URLs and only includes successful rows with images. Unsuccessful and imageless rows are skipped so they cannot clear existing images. Ingest continues through the batch after an image error and logs `processed`, `skipped`, and `failed` row counts; if any eligible row fails, it does not write a new output CSV. Completed uploads are resumable on rerun.

Author: Anthony Pham
Created: February 17, 2026
Last Updated: October 7, 2026
