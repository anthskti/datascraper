"""Reusable browser session for price-only YesStyle refreshes."""

import asyncio
import logging

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from datascraper.sources.v2.yesstyle.extractors import PRICE_SELECTOR, extract_price

logger = logging.getLogger(__name__)

NAVIGATION_RETRIES = 2
NAVIGATION_TIMEOUT_MS = 30000
READY_TIMEOUT_MS = 12000
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/119.0.0.0 Safari/537.36"
)


class YesStylePriceScraper:
    """Keep Playwright and Chromium alive across a merchant refresh batch."""

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context(user_agent=USER_AGENT)
        except Exception:
            await self.playwright.stop()
            raise
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.context.close()
        await self.browser.close()
        await self.playwright.stop()

    async def scrape_price(self, url: str) -> str:
        page = await self.context.new_page()
        last_error: Exception | None = None
        try:
            for attempt in range(1, NAVIGATION_RETRIES + 1):
                try:
                    await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=NAVIGATION_TIMEOUT_MS,
                    )
                    await page.wait_for_selector(
                        PRICE_SELECTOR,
                        timeout=READY_TIMEOUT_MS,
                    )
                    price = extract_price(BeautifulSoup(await page.content(), "html.parser"))
                    if price:
                        return price
                    last_error = ValueError("YesStyle price was not present on the product page")
                except PlaywrightTimeoutError as exc:
                    last_error = exc
                    logger.warning(
                        "Timed out loading YesStyle price for %s (attempt %d/%d)",
                        url,
                        attempt,
                        NAVIGATION_RETRIES,
                    )
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "Could not read YesStyle price for %s (attempt %d/%d): %s",
                        url,
                        attempt,
                        NAVIGATION_RETRIES,
                        exc,
                    )
                if attempt < NAVIGATION_RETRIES:
                    await asyncio.sleep(attempt * 1.5)
            raise ValueError(f"Could not extract YesStyle price from {url}") from last_error
        finally:
            await page.close()

