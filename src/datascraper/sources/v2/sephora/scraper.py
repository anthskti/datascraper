"""Reusable browser session for price-only Sephora refreshes."""

import logging

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from datascraper.sources.v2.sephora.extractors import extract_price, is_blocked

logger = logging.getLogger(__name__)

NAVIGATION_TIMEOUT_MS = 60000
PDP_READY_TIMEOUT_MS = 30000
PDP_READY_SELECTOR = '[data-at="brand_name"]'
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]
STEALTH_INIT_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


class SephoraPriceScraper:
    """Keep Playwright and Chrome alive across a merchant refresh batch."""

    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        try:
            try:
                self.browser = await self.playwright.chromium.launch(
                    channel="chrome",
                    headless=True,
                    args=LAUNCH_ARGS,
                )
            except Exception as exc:
                logger.warning(
                    "Chrome channel unavailable (%s); falling back to bundled Chromium",
                    exc,
                )
                self.browser = await self.playwright.chromium.launch(
                    headless=True,
                    args=LAUNCH_ARGS,
                )
            self.context = await self.browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 900},
                locale="en-CA",
                timezone_id="America/Toronto",
                extra_http_headers={"Accept-Language": "en-CA,en;q=0.9"},
            )
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
        try:
            await page.add_init_script(STEALTH_INIT_SCRIPT)
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            page_title = await page.title()
            if "access denied" in page_title.lower():
                raise ValueError("Sephora blocked the request (Access Denied)")

            await page.wait_for_selector(
                PDP_READY_SELECTOR,
                timeout=PDP_READY_TIMEOUT_MS,
            )
            soup = BeautifulSoup(await page.content(), "html.parser")
            if is_blocked(soup, page_title):
                raise ValueError("Sephora returned a blocked page")

            price = extract_price(soup)
            if not price:
                raise ValueError("Sephora price was not present on the product page")
            return price
        finally:
            await page.close()

