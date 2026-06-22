yesstyle_scraper.py

A async web scraper for extracting product data from YesStyle.com.
Uses Playwright for JavaScript rendering and BeautifulSoup for HTML parsing.

Author: Anthony Pham
Created: February 17, 2026
Last Updated: February 18, 2026
## Quick Start

    import asyncio
    from yesstyle_scraper import main
    asyncio.run(main())

    # Or use individual functions:
    link = await get_first_product_link("Beauty of Joseon Revive Eye Serum")
    data = await scrape_yesstyle_product(link)

## Output Schema

    {
        "title":       str,   # "Beauty of Joseon - Revive Eye Serum"
        "price":       str,   # "CA$ 18.00"
        "rating":      str,   # "4.5"
        "images":      list,  # ["https://cdn.yesstyle.com/...", ...]
        "how_to_use":  str,   # "Apply a small amount around the eye area..."
        "ingredients": str,   # "Water, Niacinamide, Adenosine..."
    }
    Missing fields default to "N/A", images defaults to [].

## Selector Strategy

    YesStyle uses CSS module hashing, meaning class names look like:
        __dKBM_W__sellingPrice
    The hash prefix (dKBM_W) changes on every site deployment, making
    exact class selectors brittle. This scraper uses partial attribute
    matching instead:
        span[class*='sellingPrice']   →  matches regardless of hash prefix
    All selectors are stored in the SELECTORS dict at the top of the file
    for easy maintenance. If the scraper breaks, inspect the live DOM and
    update SELECTORS — do not hardcode class names elsewhere.

## Known Limitations

    - Prices reflect the currency of your IP region (defaults to CA$ in Canada).
    - YesStyle may throttle or block repeated headless requests. If blocked,
      consider adding request delays or rotating user agents.
    - Lazy-loaded images use data-src instead of src; both are handled.
    - Product name is split across an <a> tag and a trailing text node in
      the DOM — handled by _extract_product_name().
    - This scraper is for personal/research use only.
      Review YesStyle's Terms of Service before any commercial or large-scale use.

## Logging

    The module uses Python's standard logging at INFO and ERROR levels.
    To suppress logs:
        logging.getLogger('yesstyle_scraper').setLevel(logging.WARNING)

"""

# ─── SELECTORS ────────────────────────────────────────────────────────────────

# Verified against YesStyle DOM on [DATE].

# Uses partial class matching (class\*='...') to survive CSS module hash changes.

# If any selector stops working, inspect the live page and update the value here.

SELECTORS = {
"price": "span[class*='sellingPrice']", # Selling price span
"brand_link": "a.notranslate[href*='/list.html/bpt']", # Brand name anchor
"rating": "a[class*='ratingCount'], a[class*='rating']", # Review summary
"product_card": "a[class*='itemContainer'], div[class*='item'] a", # Search results
"images": "div[class*='imageGallery'] img, div[class*='thumbnail'] img",
"desc_sections":"div[class*='productDescription'], div[class*='tabContent']",
}

# FUNCTIONS ────────────────────────────────────────────────────────────────

async def get_first_product_link(search_query: str) -> str | None:
"""
Searches YesStyle for a product and returns the URL of the first result.

    Navigates to the YesStyle search results page, waits for JavaScript to render, and extracts the href of the first product card found.

    Args:
        search_query (str):
            Plain-text product name. Spaces and special characters are URL-encoded automatically.
            Example: "Beauty of Joseon Revive Eye Serum"

    Returns:
        str | None:
            Absolute URL of the first product result, e.g.:
                "https://www.yesstyle.com/en/beauty-of-joseon-.../pi.123456"
            Returns None if no product card is found or the page fails to load.

    Raises:
        PlaywrightTimeoutError:
            If the page does not reach networkidle within 30 seconds.
            The function logs a warning and attempts to parse partial content rather than crashing.

    Notes:
        - Uses SELECTORS["product_card"] to locate the first result.
        - Converts relative hrefs to absolute URLs automatically.
        - If this returns None unexpectedly, log the raw HTML and verify the selector against the live search results page.
    """

async def scrape_yesstyle_product(url: str) -> dict:
"""
Scrapes structured product data from a YesStyle product detail page.

    Launches a headless Chromium browser, renders the full page JavaScript,
    then delegates HTML parsing to BeautifulSoup via helper functions.

    Args:
        url (str):
            Full absolute URL of a YesStyle product page.
            Example: "https://www.yesstyle.com/en/beauty-of-joseon-.../pi.123456"

    Returns:
        dict: Structured product data with the following keys:

            price (str):
                Displayed selling price including currency symbol and &nbsp; resolved.
                Example: "CA$ 18.00"
                Defaults to "N/A" if not found.

            rating (str):
                Average customer rating as displayed on the page.
                Example: "85%"
                Defaults to "N/A" if not found.

            images (list of str):
                Ordered, deduplicated list of product image URLs.
                Handles both src and data-src (lazy-loaded) attributes.
                Example: ["https://cdn.yesstyle.com/image1.jpg", ...]
                Defaults to [].

            how_to_use (str):
                Application instructions extracted from the product description tab.
                Header text is removed; only the body content is returned.
                Defaults to "N/A" if section is absent.

            ingredients (str):
                Full ingredient list extracted from the product description tab.
                Header text is removed; only the body content is returned.
                Defaults to "N/A" if section is absent.

    Raises:
        PlaywrightTimeoutError:
            If the page does not reach networkidle within 30 seconds.
            Logs a warning and parses partial content rather than crashing.

    Notes:
        - Browser context is always closed, even on partial load.
        - Description sections are matched by h3/h4/strong header text containing "How to Use" or "Ingredient".
    """
