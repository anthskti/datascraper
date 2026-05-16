"""
BeautifulSoup extractors for YesStyle product detail pages.
DOM / HTML parsing only — no category, label, or skin-type rules.
"""

import re
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def classes_include_fragment(classes: object, fragment: str) -> bool:
    if not classes:
        return False
    if isinstance(classes, str):
        return fragment in classes
    return any(fragment in str(part) for part in classes)


def marketing_roots(soup: BeautifulSoup) -> list | None:
    boxes = soup.find_all(
        "div",
        class_=lambda c: classes_include_fragment(c, "productInfoBox"),
    )
    if not boxes:
        return None
    outer: list = []
    for box in boxes:
        if any(o is not box and o in box.parents for o in boxes):
            continue
        outer.append(box)
    return outer if outer else None


def marketing_search_roots(soup: BeautifulSoup):
    roots = marketing_roots(soup)
    return roots if roots is not None else [soup]


def extract_section_text(soup: BeautifulSoup, header_keywords: tuple[str, ...]) -> str:
    chunks: list[str] = []
    for root in marketing_search_roots(soup):
        for tag in root.find_all(["b", "strong", "h3", "h4", "h5", "h6"]):
            label = tag.get_text(" ", strip=True).lower().rstrip(":")
            if not any(keyword in label for keyword in header_keywords):
                continue
            container = tag.find_parent(["div", "p", "li", "section"]) or tag.parent
            if not container:
                continue
            text = container.get_text(" ", strip=True)
            cleaned = re.sub(
                rf"(?i)^({'|'.join(re.escape(k) for k in header_keywords)})\s*:?\s*",
                "",
                text,
            ).strip()
            if cleaned:
                chunks.append(cleaned)
    return " ".join(chunks)


def extract_marketing_text(soup: BeautifulSoup) -> str:
    roots = marketing_roots(soup)
    if roots is not None:
        return " ".join(
            root.get_text(" ", strip=True) for root in roots if root.get_text(strip=True)
        )
    parts = [
        extract_section_text(soup, ("editor's note", "editors note")),
        extract_section_text(soup, ("features", "feature")),
        extract_section_text(soup, ("benefits", "benefit")),
    ]
    for region in soup.find_all("div", attrs={"role": "region"}):
        parts.append(region.get_text(" ", strip=True))
    return " ".join(p for p in parts if p)


def extract_product_title_from_h1(h1) -> str | None:
    brand_a = h1.find("a", class_="notranslate")
    if not brand_a:
        return None
    brand = brand_a.get_text(strip=True)
    if not brand:
        return None
    full = re.sub(r"\s+", " ", h1.get_text(" ", strip=True)).strip()
    prefix = f"{brand} - "
    if full.casefold().startswith(prefix.casefold()):
        return full[len(prefix) :].strip()
    if " - " in full:
        left, right = full.split(" - ", 1)
        if left.casefold() == brand.casefold():
            return right.strip()
    return None


def extract_product_name(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        titled = extract_product_title_from_h1(h1)
        if titled is not None:
            return titled
        return h1.get_text(" ", strip=True)
    return ""


def extract_images(soup: BeautifulSoup) -> list:
    images = []
    main = soup.find("img", {"loading": "eager", "fetchpriority": "high"})
    if main and main.get("src"):
        images.append(main["src"])
    return images


def extract_ingredients(soup: BeautifulSoup) -> str:
    for region in soup.find_all("div", {"role": "region"}):
        content_div = region.find("div", class_=lambda c: c and "accordionContent" in c)
        if not content_div:
            continue
        span = content_div.find("span")
        if not span:
            continue
        text = span.get_text(strip=True)
        if text.count(",") > 5 and any(
            term in text for term in ("Water", "Glycerin", "Extract", "Acid")
        ):
            return text
    return "N/A"


def extract_how_to_use(soup: BeautifulSoup) -> str:
    for b_tag in soup.find_all("b"):
        if "how to use" not in b_tag.get_text(strip=True).lower():
            continue
        parent = b_tag.parent
        if parent and parent.name == "p":
            next_ul = parent.find_next_sibling("ul")
            if next_ul:
                steps = [li.get_text(strip=True) for li in next_ul.find_all("li")]
                if steps:
                    return " ".join(steps)

    for b_tag in soup.find_all("b"):
        if "how to use" not in b_tag.get_text(strip=True).lower():
            continue
        steps = []
        for sibling in b_tag.next_siblings:
            if sibling.name == "b":
                break
            if sibling.name == "li":
                text = sibling.get_text(strip=True)
                if text:
                    steps.append(text)
        if steps:
            return " ".join(steps)

    logger.warning("How to Use section not found.")
    return "N/A"


def extract_rating(soup: BeautifulSoup) -> str:
    star_span = soup.find(
        "span",
        class_=lambda c: c and "ratingstar" in c and "colored" in c,
    )
    if not star_span:
        logger.warning("Rating span not found. Selector may need updating.")
        return "N/A"
    match = re.search(r"width\s*:\s*(\d+(?:\.\d+)?)px", star_span.get("style", ""))
    if not match:
        return "N/A"
    return str(round(float(match.group(1)) / 20, 2))


def extract_product_info_map(soup: BeautifulSoup) -> dict[str, str]:
    info_map: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).lower().rstrip(":")
        value = cells[1].get_text(" ", strip=True)
        if label and value:
            info_map[label] = value
    return info_map


def extract_country(soup: BeautifulSoup) -> str:
    info_map = extract_product_info_map(soup)
    return info_map.get("imported from", "N/A")


def extract_capacity(soup: BeautifulSoup) -> str:
    info_map = extract_product_info_map(soup)
    for key in ("volume", "size", "net wt", "capacity", "content"):
        if key in info_map:
            return info_map[key]

    for title in soup.select("span[class*='option-title']"):
        label = title.get_text(" ", strip=True).lower().rstrip(":")
        if label not in ("size", "volume", "capacity", "net wt", "content"):
            continue
        value_el = title.find_next_sibling("span")
        if value_el:
            value = value_el.get_text(" ", strip=True)
            if value:
                return value
        parent = title.parent
        if parent:
            parent_text = parent.get_text(" ", strip=True)
            cleaned = re.sub(
                r"(?i)^(size|volume|capacity|net wt|content)\s*:\s*",
                "",
                parent_text,
            ).strip()
            if cleaned and cleaned.lower() != label:
                return cleaned

    page_text = soup.get_text(" ", strip=True)
    match = re.search(r"\b\d+(?:\.\d+)?\s?(?:ml|g|oz|fl oz)\b", page_text, re.IGNORECASE)
    return match.group(0) if match else "N/A"
