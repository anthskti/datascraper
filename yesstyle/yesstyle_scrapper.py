"""
YesStyle product scraper — Playwright fetch + BeautifulSoup parse.

Module layout:
  yesstyle_scrapper.py   — browser navigation and scrape orchestration
  yesstyle_extractors.py — DOM field extraction (price, ingredients, marketing, …)
  product_taxonomy.py    — category, labels, skinType rules
"""

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from product_taxonomy import extract_category, extract_labels, extract_skintype
from yesstyle_extractors import (
    extract_capacity,
    extract_country,
    extract_how_to_use,
    extract_images,
    extract_ingredients,
    extract_marketing_text,
    extract_product_name,
    extract_rating,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SELECTORS = {
    "price": "span[class*='sellingPrice']",
    "brand_link": "a.notranslate[href*='/list.html/bpt']",
    "product_card": "a[href*='info.html/pid.']",
}

NAVIGATION_RETRIES = 2
NAVIGATION_TIMEOUT_MS = 30000
READY_TIMEOUT_MS = 12000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/119.0.0.0 Safari/537.36"
)
PDP_READY_SELECTOR = (
    "span[class*='sellingPrice'], ul[class*='breadcrumbs'], div[role='region']"
)
VARIANT_DIALOG_SELECTOR = (
    "#product-options-dialog-content, div[class*='productOptions'][class*='dialogContent']"
)


async def _goto_with_retries(page, url: str, ready_selector: str | None = None) -> bool:
    for attempt in range(1, NAVIGATION_RETRIES + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            if ready_selector:
                await page.wait_for_selector(ready_selector, timeout=READY_TIMEOUT_MS)
            return True
        except PlaywrightTimeoutError:
            logger.warning("Timeout loading %s (attempt %d/%d).", url, attempt, NAVIGATION_RETRIES)
            if attempt < NAVIGATION_RETRIES:
                await asyncio.sleep(attempt * 1.5)
        except Exception as exc:
            logger.warning(
                "Navigation error for %s (attempt %d/%d): %s",
                url,
                attempt,
                NAVIGATION_RETRIES,
                exc,
            )
            if attempt < NAVIGATION_RETRIES:
                await asyncio.sleep(attempt * 1.5)
    return False


async def _try_reveal_variant_options(page) -> None:
    """
    YesStyle often mounts the size dialog only after clicking the variant control.
    Open it when possible so capacity (infoCol / aria-label) is in the HTML snapshot.
    """
    if await page.locator(VARIANT_DIALOG_SELECTOR).count() > 0:
        return

    triggers = [
        "button[class*='buyOptions']",
        "span[class*='option-title']",
        "[class*='selectedOption']",
        "button:has-text('ml')",
        "button:has-text('g')",
    ]
    for selector in triggers:
        locator = page.locator(selector).first
        try:
            if await locator.count() == 0 or not await locator.is_visible():
                continue
            await locator.click(timeout=3000)
            await page.wait_for_selector(VARIANT_DIALOG_SELECTOR, timeout=5000)
            logger.info("Opened variant options via selector: %s", selector)
            return
        except Exception:
            continue


@asynccontextmanager
async def _browser_page():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        try:
            yield page
        finally:
            await browser.close()


async def get_first_product_link(search_query: str) -> str | None:
    search_url = f"https://www.yesstyle.com/en/list.html?q={quote(search_query)}"

    async with _browser_page() as page:
        await _goto_with_retries(page, search_url, ready_selector=SELECTORS["product_card"])
        content = await page.content()

    soup = BeautifulSoup(content, "html.parser")
    all_results = soup.select("a[class*='itemContainer'][href*='/info.html/pid.']")
    logger.info("Found %d product links", len(all_results))

    first_result = all_results[0] if all_results else None
    if first_result and first_result.get("href"):
        href = first_result["href"]
        return href if href.startswith("http") else f"https://www.yesstyle.com{href}"

    logger.error("No product card found. Selector: '%s'", SELECTORS["product_card"])
    return None


async def scrape_yesstyle_product(url: str, product_name: str | None = None) -> dict:
    async with _browser_page() as page:
        ready = await _goto_with_retries(page, url, ready_selector=PDP_READY_SELECTOR)
        if not ready:
            logger.warning("Product page may be partially loaded; parsing with fallback extraction.")
        await _try_reveal_variant_options(page)
        content = await page.content()

    soup = BeautifulSoup(content, "html.parser")
    data = {
        "price": "N/A",
        "rating": "N/A",
        "images": [],
        "how_to_use": "N/A",
        "ingredients": "N/A",
        "category": "N/A",
        "labels": "",
        "skinType": "N/A",
        "country": "N/A",
        "capacity": "N/A",
    }

    price_el = soup.select_one(SELECTORS["price"])
    if price_el:
        data["price"] = price_el.get_text(" ", strip=True)

    data["rating"] = extract_rating(soup)
    data["images"] = extract_images(soup)
    data["how_to_use"] = extract_how_to_use(soup)
    data["ingredients"] = extract_ingredients(soup)

    resolved_name = (product_name or "").strip() or extract_product_name(soup)
    marketing_text = extract_marketing_text(soup)

    data["category"] = extract_category(soup, product_name=resolved_name)
    data["labels"] = extract_labels(
        data["category"],
        resolved_name,
        marketing_text,
        data["ingredients"],
    )
    data["skinType"] = extract_skintype(soup)
    data["country"] = extract_country(soup)
    data["capacity"] = extract_capacity(soup, page_url=url)

    return data


async def main():
    product_name = "skin1004 Madagascar Centella Asiatica 100 Ampoule"
    logger.info("Searching for: %s", product_name)

    link = await get_first_product_link(product_name)
    if not link:
        logger.error("Could not find product link. Exiting.")
        return

    logger.info("Found link: %s", link)
    data = await scrape_yesstyle_product(link)

    for key, value in data.items():
        print(f"{key}: {value}\n")


if __name__ == "__main__":
    asyncio.run(main())
