# Sephora scraper (v1)

The Sephora source extracts product data from merchant pages. Run the batch scraper from the repository root:

```bash
uv run datascraper scrape sephora --input inputs/sephora_input.csv --output outputs/sephora_output.csv --workers 4 --delay 8
```

This full discovery source package contains `extractors.py` (DOM extraction), `scraper.py` (single-product browser flow), and `scrape.py` (CSV batch orchestration). Price-only refresh uses the separate [v2 source](../../v2/sephora/README.md).
