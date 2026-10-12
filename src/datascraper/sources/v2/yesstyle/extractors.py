"""Minimal YesStyle price extraction for refresh runs."""

from bs4 import BeautifulSoup

PRICE_SELECTOR = "span[class*='sellingPrice']"


def extract_price(soup: BeautifulSoup) -> str | None:
    price = soup.select_one(PRICE_SELECTOR)
    return price.get_text(" ", strip=True) if price else None
