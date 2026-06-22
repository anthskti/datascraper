"""
Sephora single product scraper — Playwright fetch + BeautifulSoup parse.
"""

import asyncio
import logging
import re

from sephora_extractor import (
    # Needed for labels
    extract_sephora_marketing_text,
    extract_sephora_what_it_is,
    extract_sephora_formulation,

    extract_sephora_product_name,
    extract_sephora_product_brand,
    extract_sephora_product_category,
    extract_sephora_product_labels,
    extract_sephora_product_skintype,
    # extract_sephora_product_country, # Doesn't show
    extract_sephora_product_capacity,
    extract_sephora_product_price,
    extract_sephora_product_instructions,
    extract_sephora_product_ingredients,
    extract_sephora_product_imageurls,
    extract_sephora_product_rating,
    is_sephora_page_blocked,
)

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
NAVIGATION_TIMEOUT_MS = 60000
PDP_READY_TIMEOUT_MS = 30000
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
PDP_READY_SELECTOR = '[data-at="brand_name"]'
STEALTH_INIT_SCRIPT = (
    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
)


def _blocked_result(url: str, product_id: str) -> dict:
    return {
        "s_id": product_id,
        "url": url,
        "name": "N/A",
        "brand": "N/A",
        "category": "N/A",
        "labels": "",
        "skinType": "N/A",
        "country": "N/A",
        "capacity": "N/A",
        "price": "N/A",
        "instructions": "N/A",
        "ingredients": "N/A",
        "imageUrls": [],
        "rating": "N/A",
        "status": "blocked",
    }


async def _launch_browser(playwright):
    """
    Sephora/Akamai blocks Playwright's bundled Chromium.
    Installed Google Chrome (channel='chrome') is much more reliable.
    """
    try:
        return await playwright.chromium.launch(
            channel="chrome",
            headless=True,
            args=LAUNCH_ARGS,
        )
    except Exception as exc:
        logger.warning(
            "Chrome channel unavailable (%s). Falling back to bundled Chromium — "
            "Sephora may return Access Denied.",
            exc,
        )
        return await playwright.chromium.launch(headless=True, args=LAUNCH_ARGS)


async def _expand_about_product(page) -> None:
    """About the Product is collapsed by default on many PDPs (e.g. Mario Badescu mists)."""
    try:
        about = page.locator('[data-at="about_the_product_title"]')
        if await about.count():
            await about.first.scroll_into_view_if_needed()
            await page.wait_for_timeout(500)

        show_more = page.locator("#details").get_by_role(
            "button", name=re.compile(r"show more", re.IGNORECASE)
        )
        if await show_more.count():
            await show_more.first.click(timeout=3000)
            await page.wait_for_timeout(800)

        await page.wait_for_selector(
            "#details p strong, #details b",
            timeout=8000,
        )
    except PlaywrightTimeoutError:
        logger.warning("About the Product section may be incomplete in HTML snapshot.")
    except Exception:
        logger.debug("Could not fully expand About the Product.")


async def _expand_product_tabs(page) -> None:
    """Ingredients / How to Use are often collapsed until their tab is clicked."""
    for label in ("Ingredients", "How to Use"):
        try:
            button = page.get_by_role("button", name=label, exact=True)
            if await button.count() == 0:
                continue
            await button.first.click(timeout=3000)
            await page.wait_for_timeout(800)
        except Exception:
            logger.debug("Could not open tab: %s", label)


async def _fetch_product_html(url: str) -> tuple[str | None, str | None]:
    async with async_playwright() as playwright:
        browser = await _launch_browser(playwright)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="en-CA",
            timezone_id="America/Toronto",
            extra_http_headers={"Accept-Language": "en-CA,en;q=0.9"},
        )
        page = await context.new_page()
        await page.add_init_script(STEALTH_INIT_SCRIPT)

        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            page_title = await page.title()
            if is_sephora_page_blocked(None, page_title=page_title):
                logger.error("Sephora blocked this request (Access Denied).")
                return None, page_title

            await page.wait_for_selector(
                PDP_READY_SELECTOR,
                timeout=PDP_READY_TIMEOUT_MS,
            )

            try:
                await page.wait_for_selector(
                    '[data-at="selected_swatch"]',
                    timeout=8000,
                )
            except PlaywrightTimeoutError:
                logger.warning("Selected swatch not found before timeout.")

            await _expand_about_product(page)

            for section_id in ("ingredients_section", "ingredients", "how_to_use_section"):
                locator = page.locator(f"#{section_id}")
                if await locator.count():
                    await locator.scroll_into_view_if_needed()

            await _expand_product_tabs(page)

            try:
                await page.wait_for_selector(
                    "#ingredients_section, #ingredients",
                    timeout=5000,
                )
            except PlaywrightTimeoutError:
                pass

            try:
                await page.get_by_text("Ratings", exact=False).first.scroll_into_view_if_needed()
            except Exception:
                pass

            await page.wait_for_timeout(1500)
            return await page.content(), page_title
        except PlaywrightTimeoutError as exc:
            logger.error("Timed out loading Sephora PDP: %s", exc)
            return None, await page.title()
        except Exception as exc:
            logger.error("Failed to load %s: %s", url, exc)
            return None, None
        finally:
            await browser.close()


async def scrape_sephora_product(url: str, product_id: str) -> dict:
    content, page_title = await _fetch_product_html(url)
    if not content:
        return _blocked_result(url, product_id)

    soup = BeautifulSoup(content, "html.parser")
    if is_sephora_page_blocked(soup, page_title=page_title):
        logger.error(
            "Sephora returned a bot-block page (%d bytes). Use Chrome via Playwright "
            "and retry; residential proxies may be needed at scale.",
            len(content),
        )
        return _blocked_result(url, product_id)

    resolved_name = extract_sephora_product_name(soup, page_url=url)
    what_it_is = extract_sephora_what_it_is(soup)
    marketing_text = extract_sephora_marketing_text(soup)
    ingredients = extract_sephora_product_ingredients(soup)
    category = extract_sephora_product_category(
        soup, product_name=resolved_name, page_url=url
    )

    data = {
        "s_id": product_id,
        "url": url,
        "name": resolved_name,
        "brand": extract_sephora_product_brand(soup),
        "category": category,
        "labels": extract_sephora_product_labels(
            category,
            resolved_name,
            marketing_text,
            ingredients,
            description_text=what_it_is,
            formulation_text=extract_sephora_formulation(soup),
        ),
        "skinType": extract_sephora_product_skintype(soup),
        "country": "N/A",
        "capacity": extract_sephora_product_capacity(soup),
        "price": extract_sephora_product_price(soup),
        "instructions": extract_sephora_product_instructions(soup),
        "ingredients": ingredients,
        "imageUrls": extract_sephora_product_imageurls(soup),
        "rating": extract_sephora_product_rating(soup),
        "status": "success",
    }

    if data["brand"] == "N/A":
        logger.warning("PDP loaded but brand missing — marking scrape as partial.")
        data["status"] = "partial"

    return data


async def main():
    product_id = "P7880"
    url = (
        "https://www.sephora.com/ca/en/product/soy-face-cleanser-P7880"
    )
    logger.info("Going to URL: %s", url)

    data = await scrape_sephora_product(url, product_id)
    for key, value in data.items():
        print(f"{key}: {value}\n")


if __name__ == "__main__":
    asyncio.run(main())
