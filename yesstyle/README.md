# Yesstyle Scrapper Information

- `yesstyle_extractors.py`: Helper methods that get specific information from the DOM. Any changes to YesStyle's webpage itself, we can update it here. Ex. wanting to finetune skintypes as they add a new "skin type" section in product details, can update soup to pick it up. `product_taxonomy` helps generalize key words to fit my databases context.
- `yesstyle_scrapper.py`: Gets **singular product information** using information from yesstyle_extractors.
- `scrape_yesstyle.py`: From `inputs/yesstyle_input.csv` (Brand, Name), extracts each line from it and calls yesstyle_scrapper to get its information.

## How to Run

Test 1 product in yesstyle_scrapper (usually for testing):
```bash
uv run python yesstyle/yesstyle_scrapper.py
```

Run Pipeline (need `inputs/yesstyle_input.csv`):
```bash
uv run python yesstyle/scrape_yesstyle.py
```

CLI inputs for `--input`, `--output`, `--workers`, `--delay`:
```bash
uv run python yesstyle/scrape_yesstyle.py --input --output --workers --delay
```

## Notes
- Yesstyle is inconsistent with skin types, they sometimes have a "skin type" description, but sometimes I pull it from the product details section. This can cause descreptencies.
- I can only grab one image, as yesstyles images are a little weird.
- **TODO: have to update the pipeline to support toner pads and liquid toners**
