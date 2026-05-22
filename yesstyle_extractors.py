"""
BeautifulSoup extractors for YesStyle product detail pages.
DOM / HTML parsing only — no category, label, or skin-type rules.
"""

import re
import logging
from bs4 import BeautifulSoup, NavigableString

logger = logging.getLogger(__name__)

# Dropdown "productOptions" for capacity extraction. ex "2025 Version - 200ml" → 200ml
_CAPACITY_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?\s*(?:ml|g|oz|fl\.?\s*oz))\b",
    re.IGNORECASE,
)
_NUMBERED_STEP_PREFIX = re.compile(r"^\d+\.\s*")
_NUMBERED_STEP_INLINE = re.compile(r"\s+\d+\.\s+")


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
        if bool(text) and text.count(",") > 5:
            return text
    return "N/A"


def _strip_numbered_step_prefix(text: str) -> str:
    text = _NUMBERED_STEP_PREFIX.sub("", text)
    text = _NUMBERED_STEP_INLINE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _collect_text_after_how_to_use_heading(b_tag) -> str:
    """
    YesStyle often uses numbered plain text after <br>, not <ul><li>.
    Example: extra/instructionexample.md
    """
    parts: list[str] = []
    for sibling in b_tag.next_siblings:
        if getattr(sibling, "name", None) == "b":
            break
        if isinstance(sibling, NavigableString):
            text = _strip_numbered_step_prefix(str(sibling))
        elif getattr(sibling, "name", None) == "br":
            continue
        else:
            text = _strip_numbered_step_prefix(sibling.get_text(" ", strip=True))
        if text:
            parts.append(text)
    joined = " ".join(parts)
    return _strip_numbered_step_prefix(joined)


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
        # Since Yesstyle has different ways of checking for how to use, we need to check for all possible ways.
        for sibling in b_tag.next_siblings:
            if getattr(sibling, "name", None) == "b":
                break
            if getattr(sibling, "name", None) == "li":
                text = sibling.get_text(strip=True)
                if text:
                    steps.append(text)
        if steps:
            return " ".join(steps)

        inline = _collect_text_after_how_to_use_heading(b_tag)
        if inline:
            return inline

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


def _parse_capacity_from_text(text: str) -> str | None:
    match = _CAPACITY_PATTERN.search(text)
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(1))


def _is_variant_header_label(text: str) -> bool:
    lower = text.lower()
    return (
        "usually ships" in lower
        or lower in ("price", "option", "size", "color")
        or lower.startswith("option/")
    )


def _capacity_from_variant_label(text: str) -> str | None:
    if not text or _is_variant_header_label(text):
        return None
    return _parse_capacity_from_text(text)


def _extract_capacity_from_product_options(soup: BeautifulSoup) -> str | None:
    """
    YesStyle size/color picker (modal or inline).

    Reliable sources (see extra/anuaheartleaf.md):
      - button[aria-label] on variant rows, e.g. aria-label="2025 Version - 200ml"
      - div[class*='infoCol'] inside option buttons (not the header row)
    """
    for button in soup.select("button[aria-label][class*='options']"):
        capacity = _capacity_from_variant_label(button.get("aria-label", ""))
        if capacity:
            return capacity
    #  Checks productOptions -> infoCol for modal access
    for button in soup.find_all("button", class_=lambda c: classes_include_fragment(c, "productOptions")):
        if not classes_include_fragment(button.get("class"), "options"):
            continue
        capacity = _capacity_from_variant_label(button.get("aria-label", ""))
        if capacity:
            return capacity

    for button in soup.select("button[class*='options']"):
        info_col = button.find(
            ["motion", "div"],
            class_=lambda c: classes_include_fragment(c, "infoCol"),
        )
        if not info_col:
            continue
        capacity = _capacity_from_variant_label(info_col.get_text(" ", strip=True))
        if capacity:
            return capacity

    dialog = soup.select_one(
        "#product-options-dialog-content, div[class*='dialogContent'][class*='productOptions']"
    )
    if dialog:
        for info_col in dialog.select("motion[class*='infoCol'], div[class*='infoCol']"):
            capacity = _capacity_from_variant_label(info_col.get_text(" ", strip=True))
            if capacity:
                return capacity

    return None


def _extract_capacity_from_url(page_url: str | None) -> str | None:
    if not page_url:
        return None
    return _parse_capacity_from_text(page_url)


def extract_capacity(soup: BeautifulSoup, page_url: str | None = None) -> str:
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

    from_options = _extract_capacity_from_product_options(soup)
    if from_options:
        return from_options

    from_url = _extract_capacity_from_url(page_url)
    if from_url:
        return from_url

    page_text = soup.get_text(" ", strip=True)
    return _parse_capacity_from_text(page_text) or "N/A"
