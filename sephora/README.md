# Sephora Scrapper Information

- `sephora_extractor.py`: Helper method that gets specific information from the DOM. Any changes to sephora webpage itself, we can update it here. Ex. if they add a country section, we can update it. `product_taxonomy` helps generalize key words to fit my databases context.
- `sephora_scrapper.py`: Gets **singular product information** using information from sephora_extractor.
- `scrape_sephora.py`: From `inputs/sephora_input.csv` (product_id, url), extracts each line from it and calls sephora_scrapper to get its information.

## How to Run

Test 1 product in sephora_scrapper (usually for testing):
```bash
uv run python sephora/sephora_scrapper.py
```

Run Pipeline (need `inputs/sephora_input.csv`):
```bash
uv run python sephora/scrape_sephora.py
```

CLI inputs for `--input`, `--output`, `--workers`, `--delay`:
```bash
uv run python sephora/scrape_sephora.py --input --output --workers --delay
```

## Notes
- Sephora does not show country flag anywhere, so I'll likely have to manually apply it myself. Will organize the spreadsheet in brand order to multiple add country of origin.
- The skin types on sephora do not cover all my skintypes, so I generalize:
    - oily + combination = acne-prone
    - dry = sensitive
- Product name will be a little ambigious and might need updating, Sephora runs key words in their name, that's why I have a filter to remove specific words after the title like for.
