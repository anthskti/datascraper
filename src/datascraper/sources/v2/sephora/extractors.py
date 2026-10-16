"""Minimal Sephora price extraction for refresh runs."""

import re

from bs4 import BeautifulSoup

_PRICE_RE = re.compile(r"^\$[\d,]+(?:\.\d{2})?$")


def extract_price(soup: BeautifulSoup) -> str | None:
    price_el = soup.find(attrs={"data-at": "price"})
    if price_el:
        text = price_el.get_text(strip=True)
        if text:
            return text

    for span in soup.find_all("span"):
        for bold in span.find_all("b", recursive=False):
            text = bold.get_text(strip=True)
            if _PRICE_RE.match(text):
                return text

    match = re.search(r"\$\d+(?:\.\d{2})?", soup.get_text(" ", strip=True))
    return match.group(0) if match else None


def is_blocked(soup: BeautifulSoup, page_title: str) -> bool:
    if "access denied" in page_title.lower():
        return True
    text = soup.get_text(" ", strip=True).lower()
    return "access denied" in text and len(text) < 600
