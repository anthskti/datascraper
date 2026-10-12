# YesStyle scraper (v1)

The YesStyle source extracts product data from merchant pages. Run the batch scraper from the repository root:

```bash
uv run datascraper scrape yesstyle --input inputs/yesstyle_input_v2.csv --output outputs/yesstyle_output.csv --workers 5 --delay 5
```

This full discovery source package contains `extractors.py` (DOM extraction), `scraper.py` (single-product browser flow), and `scrape.py` (CSV batch orchestration). YesStyle currently extracts one image per product. Price-only refresh uses the separate [v2 source](../../v2/yesstyle/README.md).
