# Product Data Scraper for Clearup 

This repository is a compliment to [Clearup.skin](https://www.clearup.skin)([repo](https://github.com/anthskti/ClearUp)).

Currently focuses on these retail stores:
1. [YesStyle](src/datascraper/sources/yesstyle/README.md) — drawback: skin types are inconsistent.
2. [Sephora](src/datascraper/sources/sephora/README.md) — drawback: doesn't state country.

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

Use `uv run datascraper --help` or `uv run datascraper scrape --help` for options. The shared output schema is in `datascraper.models`; merchant modules live under `src/datascraper/sources/`.

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

R2 product keys use a SHA-256 digest of the trimmed, lowercased `brand::name` identity, followed by the image position and source-URL digest. Scraper CSVs retain their original merchant image URLs; the derived import CSV contains R2 URLs and only includes successful rows with images. Unsuccessful and imageless rows are skipped so they cannot clear existing images. Ingest stops without writing a completed CSV if any eligible image fails, and can resume completed uploads on rerun.

Author: Anthony Pham
Created: February 17, 2026
Last Updated: October 7, 2026
