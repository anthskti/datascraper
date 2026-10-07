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

Author: Anthony Pham
Created: February 17, 2026
Last Updated: October 7, 2026
