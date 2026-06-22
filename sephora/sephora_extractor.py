"""
BeautifulSoup extractors for Sephora product detail pages.
DOM / HTML parsing only — category/label/skin-type rules live in product_taxonomy.
"""

import json
import re
import logging
import sys
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from product_taxonomy import (
    ALL_SKIN_TYPES,
    _extract_category_from_name,
    _extract_skin_types_from_text,
    _map_breadcrumb_to_category,
    extract_labels,
)

logger = logging.getLogger(__name__)

_PRODUCT_SLUG_RE = re.compile(r"/product/(.+)-P\d+", re.IGNORECASE)
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200d\ufeff]")
_PRICE_RE = re.compile(r"^\$[\d,]+(?:\.\d{2})?$")
_RATING_RE = re.compile(r"^\d+(?:\.\d+)?$")
_ML_CAPACITY_RE = re.compile(r"(\d+(?:\.\d+)?)\s*ml\b", re.IGNORECASE)
_OZ_CAPACITY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:fl\.?\s*)?oz\b",
    re.IGNORECASE,
)
_NUMBERED_STEP_PREFIX = re.compile(r"^\d+\.\s*")
_NUMBERED_STEP_INLINE = re.compile(r"\s+\d+\.\s+")
_INSTRUCTION_BULLET_START = re.compile(r"^-\s*")
_INSTRUCTION_BULLET_AFTER_SENTENCE = re.compile(r"(?<=[.!?])-\s*")
_INSTRUCTION_BULLET_AFTER_SPACE = re.compile(r"(?<=\s)-\s*")

# Product name cleanup (Sephora PDP titles are marketing-heavy)
# Truncate at the first whole-word match; everything from that word onward is dropped.
# Note: ("for") is a str, not a tuple — always use a trailing comma: ("for",).
NAME_TRUNCATE_AT: tuple[str, ...] = ("for",)

# Remove these whole words anywhere in the remaining name (country/marketing fluff).
NAME_STRIP_WORDS: tuple[str, ...] = ("korean", "daily")


def _normalize_raw_product_name(text: str) -> str:
    cleaned = _ZERO_WIDTH_RE.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def _truncate_product_name(name: str, markers: tuple[str, ...] = NAME_TRUNCATE_AT) -> str:
    """Keep text before the earliest truncate marker (e.g. 'for', 'with')."""
    cut_at = len(name)
    for marker in markers:
        match = re.search(rf"\b{re.escape(marker)}\b", name, flags=re.IGNORECASE)
        if match and match.start() < cut_at:
            cut_at = match.start()
    return name[:cut_at].strip().rstrip("-–—,:; ")


def _strip_product_name_words(
    name: str, words: tuple[str, ...] = NAME_STRIP_WORDS
) -> str:
    for word in words:
        name = re.sub(rf"\b{re.escape(word)}\b", "", name, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", name).strip()


def _clean_sephora_product_name(raw: str) -> str:
    name = _normalize_raw_product_name(raw)
    name = _truncate_product_name(name)
    name = _strip_product_name_words(name)
    return name


def _raw_name_from_og_title(content: str) -> str | None:
    """Fallback: drop ' - Brand | Sephora' suffix from og:title."""
    title = content.strip()
    if " | " in title:
        title = title.split(" | ", 1)[0]
    if " - " in title:
        title = title.rsplit(" - ", 1)[0]
    return _clean_sephora_product_name(title) if title else None


def _page_url(soup: BeautifulSoup, page_url: str | None = None) -> str | None:
    if page_url:
        return page_url
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        return canonical["href"]
    og_url = soup.find("meta", property="og:url")
    if og_url and og_url.get("content"):
        return og_url["content"]
    return None


def _name_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _PRODUCT_SLUG_RE.search(url)
    if not match:
        return None
    return match.group(1).replace("-", " ").strip().title()


def _find_section_root(soup: BeautifulSoup, section_id: str):
    return soup.find(id=section_id)


def _ingredients_section_root(soup: BeautifulSoup):
    """Sephora uses #ingredients_section or #ingredients depending on the PDP layout."""
    return _find_section_root(soup, "ingredients_section") or _find_section_root(
        soup, "ingredients"
    )


def _chunks_split_by_double_br(element) -> list[str]:
    """Text chunks separated by two consecutive <br> tags (Mario inline layout)."""
    chunks: list[str] = []
    buf: list[str] = []
    br_run = 0

    def flush() -> None:
        nonlocal buf, br_run
        text = re.sub(r"\s+", " ", "".join(buf)).strip()
        buf = []
        br_run = 0
        if text:
            chunks.append(text)

    for child in element.children:
        if getattr(child, "name", None) == "br":
            br_run += 1
            if br_run >= 2:
                flush()
            continue
        if br_run == 1:
            buf.append(" ")
        br_run = 0
        if isinstance(child, NavigableString):
            buf.append(str(child))
        elif getattr(child, "name", None) is not None:
            buf.append(child.get_text(" ", strip=False))

    flush()
    return chunks


def _details_root(soup: BeautifulSoup):
    return _find_section_root(soup, "details")


def _about_product_root(soup: BeautifulSoup):
    """
    Scope label/copy extraction to About the Product — not the full PDP.

    Sephora uses <strong> or <b> labels — often inline in one <div> with <br />
    separators (e.g. Mario Badescu), not always one <p> per field.
    """
    details = _details_root(soup)
    if details:
        return details

    heading = soup.find(attrs={"data-at": "about_the_product_title"})
    if heading:
        container = heading.find_parent("div")
        if container:
            return container

    for label_tag in soup.find_all(["strong", "b"]):
        label = label_tag.get_text(" ", strip=True).lower().rstrip(":")
        if "what it is" not in label:
            continue
        block = label_tag.find_parent("div")
        if block:
            return block

    return None


def _extract_sephora_breadcrumb_labels(soup: BeautifulSoup) -> list[str]:
    crumbs: list[str] = []
    for anchor in soup.find_all("a", attrs={"data-at": "pdp_bread_crumb"}):
        text = anchor.get_text(strip=True)
        if text and text.lower() != "home":
            crumbs.append(text)
    return crumbs


def _value_after_label_tag(label_tag) -> str:
    """
    Text after a <strong> or <b> field label.

    Innisfree style: <p><strong>What it is:</strong> blurb</p>
    Mario style:    <div><b>What it is:</b> blurb<br><b>Skin Type:</b> ...
    """
    parent = label_tag.parent
    if not parent:
        return ""

    label = label_tag.get_text(" ", strip=True)

    if parent.name == "p":
        full = parent.get_text(" ", strip=True)
        cleaned = re.sub(
            rf"(?i)^{re.escape(label)}\s*:?\s*",
            "",
            full,
        ).strip()
        return cleaned

    parts: list[str] = []
    for sibling in label_tag.next_siblings:
        if getattr(sibling, "name", None) in ("b", "strong"):
            break
        if isinstance(sibling, NavigableString):
            text = str(sibling).strip()
        elif getattr(sibling, "name", None) == "br":
            if parts and not parts[-1].endswith(" "):
                parts.append(" ")
            continue
        else:
            text = sibling.get_text(" ", strip=True)
        if text:
            parts.append(text)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _value_after_strong_tag(strong_tag) -> str:
    return _value_after_label_tag(strong_tag)


def _extract_labeled_field_from_details(
    soup: BeautifulSoup, label_keywords: tuple[str, ...]
) -> str:
    root = _about_product_root(soup) or soup

    for label_tag in root.find_all(["strong", "b"]):
        label = label_tag.get_text(" ", strip=True).lower().rstrip(":")
        if not any(keyword in label for keyword in label_keywords):
            continue
        value = _value_after_label_tag(label_tag)
        if value:
            return value
    return ""


def _normalize_skintype_text(text: str) -> str:
    normalized = text.replace("Combo", "Combination").replace("combo", "combination")
    normalized = normalized.replace("&", " and ")
    return normalized


def _generalize_sephora_skintypes(types: list[str]) -> list[str]:
    """
    Sephora often omits inferred types — fill common gaps from listed ones.

    - combination + oily → acne-prone
    - dry → sensitive
    """
    inferred = set(types)
    if "combination" in inferred and "oily" in inferred:
        inferred.add("acne-prone")
    if "dry" in inferred:
        inferred.add("sensitive")
    return [skin for skin in ALL_SKIN_TYPES if skin in inferred]


def _format_skintype_list(types: list[str]) -> str:
    if not types:
        return "N/A"
    return ", ".join(_generalize_sephora_skintypes(types))


def _strip_numbered_step_prefix(text: str) -> str:
    text = _NUMBERED_STEP_PREFIX.sub("", text)
    text = _NUMBERED_STEP_INLINE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_instructions(text: str) -> str:
    """
    Flatten Sephora usage bullets into prose.

    Handles both "- After serum..." and "-Mist onto..." / ".-Use to boost...".
  """
    text = _strip_numbered_step_prefix(text)
    text = _INSTRUCTION_BULLET_START.sub("", text)
    text = _INSTRUCTION_BULLET_AFTER_SENTENCE.sub(" ", text)
    text = _INSTRUCTION_BULLET_AFTER_SPACE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _collect_text_after_heading(heading_tag) -> str:
    parts: list[str] = []
    for sibling in heading_tag.next_siblings:
        if getattr(sibling, "name", None) in ("strong", "b", "h2", "h3", "h4"):
            break
        if isinstance(sibling, NavigableString):
            text = _strip_numbered_step_prefix(str(sibling))
        elif getattr(sibling, "name", None) == "br":
            if parts and not parts[-1].endswith(" "):
                parts.append(" ")
            continue
        else:
            text = _strip_numbered_step_prefix(sibling.get_text(" ", strip=True))
        if text:
            parts.append(text)
    return _strip_numbered_step_prefix(" ".join(parts))


def _format_capacity_amount(value: str) -> str:
    if value.endswith(".0"):
        value = value[:-2]
    return value


def _normalize_capacity(raw: str) -> str | None:
    """Prefer ml when present; otherwise return oz (e.g. Paula's Choice 1oz)."""
    text = raw.strip()
    if not text:
        return None

    ml_match = _ML_CAPACITY_RE.search(text)
    if ml_match:
        return f"{_format_capacity_amount(ml_match.group(1))}ml"

    oz_match = _OZ_CAPACITY_RE.search(text)
    if oz_match:
        return f"{_format_capacity_amount(oz_match.group(1))}oz"

    if "/" in text:
        for segment in text.split("/"):
            capacity = _normalize_capacity(segment.strip())
            if capacity:
                return capacity

    return None


def _normalize_capacity_ml(raw: str) -> str | None:
    return _normalize_capacity(raw)


def _looks_like_ingredient_list(text: str) -> bool:
    cleaned = text.strip()
    if not cleaned or cleaned.startswith("-"):
        return False
    if cleaned.count(",") < 8:
        return False
    core = re.sub(r"\([^)]*\)", "", cleaned)
    lower = core.lower()
    if re.search(r"\b(this|these|product|moisturizer|cream|vegan|barrier|hydration)\b", lower):
        return False
    return True


_OTHER_INGREDIENT_LABELS = ("other ingredients", "inactive ingredients")
_ACTIVE_INGREDIENT_LABELS = ("active ingredients",)


def _parse_ingredient_labeled_text(text: str) -> tuple[str | None, str]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    lower = cleaned.lower()
    for label in _OTHER_INGREDIENT_LABELS:
        if lower.startswith(label):
            value = re.sub(rf"(?i)^{re.escape(label)}\s*:?\s*", "", cleaned).strip()
            return "other", value
    for label in _ACTIVE_INGREDIENT_LABELS:
        if lower.startswith(label):
            value = re.sub(rf"(?i)^{re.escape(label)}\s*:?\s*", "", cleaned).strip()
            return "active", value
    return None, cleaned


def _clean_ingredient_list_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(
        r"\s*\(\s*sunscreen actives\s*\)\s*\.?\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return text.rstrip(".").strip()


def _ingredient_token_key(token: str) -> str:
    """Normalize one INCI entry for overlap checks."""
    key = token.strip().lower()
    key = re.split(r"\s*\(", key, maxsplit=1)[0].strip()
    key = re.sub(r"\s*\d+(?:\.\d+)?\s*%", "", key).strip()
    return key


def _ingredient_lists_overlap(active: str, other: str) -> bool:
    active_lower = active.lower().strip()
    other_lower = other.lower().strip()
    if active_lower in other_lower or other_lower in active_lower:
        return True

    active_tokens = {
        key for part in active.split(",") if (key := _ingredient_token_key(part))
    }
    other_tokens = {
        key for part in other.split(",") if (key := _ingredient_token_key(part))
    }
    return bool(active_tokens & other_tokens)


def _merge_labeled_ingredient_sections(
    active: str | None, other: str | None
) -> str | None:
    if active and other:
        if _ingredient_lists_overlap(active, other):
            return other if len(other) >= len(active) else active
        return f"{active}, {other}"
    return other or active


def _ingredients_from_labeled_sections(root) -> str | None:
    """
    Paula's Choice / some sunscreens: separate Active vs Other (or Inactive) blocks.
    Merge both when they don't overlap; otherwise keep the fuller list.
    """
    other: str | None = None
    active: str | None = None

    def consider(kind: str | None, value: str) -> None:
        nonlocal other, active
        if not kind or not value:
            return
        cleaned = _clean_ingredient_list_text(value)
        if kind == "other":
            other = cleaned
        elif kind == "active":
            active = cleaned

    for paragraph in root.find_all("p"):
        if paragraph.find("em"):
            continue
        text = paragraph.get_text(" ", strip=True)
        consider(*_parse_ingredient_labeled_text(text))

    for div in root.find_all("div"):
        for chunk in _chunks_split_by_double_br(div):
            consider(*_parse_ingredient_labeled_text(chunk))

    return _merge_labeled_ingredient_sections(active, other)


def is_sephora_page_blocked(
    soup: BeautifulSoup | None, *, page_title: str | None = None
) -> bool:
    """True when Akamai serves the tiny Access Denied page instead of the PDP."""
    if page_title and "access denied" in page_title.lower():
        return True
    if soup is None:
        return False
    text = soup.get_text(" ", strip=True).lower()
    if "access denied" in text and len(text) < 600:
        return True
    if not soup.find(attrs={"data-at": "brand_name"}) and not soup.find(id="details"):
        return True
    return False


def _iter_json_ld_objects(soup: BeautifulSoup):
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            payload = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            yield from payload
        else:
            yield payload


def _format_rating(value: str) -> str:
    try:
        return str(round(float(value), 1))
    except ValueError:
        return value


def _rating_from_json_ld(soup: BeautifulSoup) -> str | None:
    for item in _iter_json_ld_objects(soup):
        if item.get("@type") not in ("Product", "ProductGroup"):
            continue
        aggregate = item.get("aggregateRating") or {}
        rating = aggregate.get("ratingValue")
        if rating is not None:
            return _format_rating(str(rating).strip())
    return None


def _page_product_json_blob(soup: BeautifulSoup) -> str:
    markers = (
        '"page":{"product"',
        '"whatItIs"',
        '"ingredientDesc"',
        '"suggestedUsage"',
    )
    for script in soup.find_all("script"):
        text = script.string or ""
        if any(marker in text for marker in markers):
            return text
    return ""


def _extract_labeled_field_from_json_blob(
    blob: str,
    label_keywords: tuple[str, ...],
    fields: tuple[str, ...],
) -> str:
    """Parse embedded product JSON HTML blocks (full About-the-Product copy)."""
    if not blob:
        return ""

    for field in fields:
        raw = _extract_json_string_field(blob, field)
        if not raw:
            continue
        if "<" in raw:
            fragment = BeautifulSoup(raw, "html.parser")
            value = _extract_labeled_field_from_details(fragment, label_keywords)
            if value:
                return value
        text = _html_fragment_to_text(raw)
        if text and label_keywords == ("what it is",):
            return text
    return ""


WHAT_IT_IS_JSON_FIELDS = (
    "whatItIs",
    "what_it_is",
    "productShortDescription",
    "shortDescription",
)
INGREDIENT_JSON_FIELDS = ("ingredientDesc", "ingredients", "ingredientDescription")


def _extract_json_string_field(blob: str, field: str) -> str | None:
    match = re.search(
        rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"',
        blob,
    )
    if not match:
        return None
    raw = match.group(1)
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return (
            raw.replace("\\n", " ")
            .replace("\\r", " ")
            .replace('\\"', '"')
            .replace("\\/", "/")
            .strip()
        )


def _html_fragment_to_text(html_fragment: str) -> str:
    if not html_fragment:
        return ""
    if "<" not in html_fragment:
        return html_fragment.strip()
    return BeautifulSoup(html_fragment, "html.parser").get_text(" ", strip=True)


def _ingredients_from_html_fragment(html_fragment: str) -> str | None:
    soup = BeautifulSoup(html_fragment, "html.parser")
    return _ingredients_from_root(soup)


def _ingredients_from_root(root) -> str | None:
    """Comma-heavy INCI list from <p> paragraphs or inline <div> after callouts."""
    if not root:
        return None

    labeled = _ingredients_from_labeled_sections(root)
    if labeled:
        return labeled

    best: str | None = None
    best_commas = 0

    for paragraph in root.find_all("p"):
        if paragraph.find("em"):
            continue
        text = paragraph.get_text(" ", strip=True)
        if _looks_like_ingredient_list(text) and text.count(",") > best_commas:
            best = text
            best_commas = text.count(",")

    for div in root.find_all("div"):
        for chunk in _chunks_split_by_double_br(div):
            if _looks_like_ingredient_list(chunk) and chunk.count(",") > best_commas:
                best = chunk
                best_commas = chunk.count(",")

    return best


def _instructions_from_html_fragment(html_fragment: str) -> str | None:
    soup = BeautifulSoup(html_fragment, "html.parser")
    for label_tag in soup.find_all(["strong", "b"]):
        label = label_tag.get_text(" ", strip=True).lower().rstrip(":")
        if label != "suggested usage":
            continue
        steps: list[str] = []
        for paragraph in label_tag.parent.find_next_siblings("p"):
            text = paragraph.get_text(" ", strip=True)
            if not text or text.lower().startswith("recycling"):
                break
            steps.append(_normalize_instructions(text))
        if steps:
            return " ".join(steps)

    text = _html_fragment_to_text(html_fragment)
    return _normalize_instructions(text) if text else None


def extract_sephora_what_it_is(soup: BeautifulSoup) -> str:
    """Primary label source: About the Product → What it is."""
    value = _extract_labeled_field_from_details(soup, ("what it is",))
    if value:
        return value

    blob = _page_product_json_blob(soup)
    return _extract_labeled_field_from_json_blob(
        blob, ("what it is",), WHAT_IT_IS_JSON_FIELDS
    )


def extract_sephora_formulation(soup: BeautifulSoup) -> str:
    """About the Product → Formulation (e.g. Gel, Foam, Lightweight Cream)."""
    return _extract_labeled_field_from_details(soup, ("formulation",))


def extract_sephora_marketing_text(soup: BeautifulSoup) -> str:
    """Marketing copy from About the Product for taxonomy label rules."""
    parts = [
        extract_sephora_what_it_is(soup),
        _extract_labeled_field_from_details(soup, ("what else you need to know",)),
        extract_sephora_formulation(soup),
        _extract_labeled_field_from_details(soup, ("highlighted ingredients",)),
    ]
    return " ".join(part for part in parts if part)


def extract_sephora_product_name(
    soup: BeautifulSoup, page_url: str | None = None
) -> str:
    """
    Product name from data-at="product_name", then cleaned via NAME_TRUNCATE_AT /
    NAME_STRIP_WORDS. URL slug is last-resort fallback only.
    """
    name_el = soup.find(attrs={"data-at": "product_name"})
    if name_el:
        cleaned = _clean_sephora_product_name(name_el.get_text(" ", strip=True))
        if cleaned:
            return cleaned

    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        from_og = _raw_name_from_og_title(og_title["content"])
        if from_og:
            return from_og

    url = _page_url(soup, page_url=page_url)
    name = _name_from_url(url)
    if name:
        return _clean_sephora_product_name(name)

    logger.warning("Product name not found (data-at=product_name).")
    return "N/A"


def extract_sephora_product_brand(soup: BeautifulSoup) -> str:
    brand_link = soup.find("a", attrs={"data-at": "brand_name"})
    if brand_link:
        brand = brand_link.get_text(strip=True)
        if brand:
            return brand

    logger.warning("Brand not found (data-at=brand_name).")
    return "N/A"


def extract_sephora_product_category(
    soup: BeautifulSoup,
    product_name: str | None = None,
    page_url: str | None = None,
) -> str:
    """Category from product name first, then Sephora breadcrumbs."""
    name = (product_name or "").strip() or extract_sephora_product_name(
        soup, page_url=page_url
    )
    if name and name != "N/A":
        from_name = _extract_category_from_name(name)
        if from_name:
            return from_name

    for crumb in reversed(_extract_sephora_breadcrumb_labels(soup)):
        mapped = _map_breadcrumb_to_category(crumb)
        if mapped != "other":
            return mapped

    return "other"


def extract_sephora_product_labels(
    category: str,
    product_name: str,
    marketing_text: str,
    ingredients: str,
    description_text: str | None = None,
    formulation_text: str | None = None,
) -> str:
    return extract_labels(
        category,
        product_name,
        marketing_text,
        ingredients,
        description_text=description_text,
        formulation_text=formulation_text,
    )


def _extract_skintype_from_root(root) -> str | None:
    for label_tag in root.find_all(["strong", "b"]):
        label = label_tag.get_text(" ", strip=True).lower().rstrip(":")
        if label != "skin type":
            continue
        value = _normalize_skintype_text(_value_after_label_tag(label_tag))
        types = _extract_skin_types_from_text(value)
        if types:
            return _format_skintype_list(types)

    for span in root.find_all("span"):
        text = span.get_text(strip=True)
        if not re.match(r"(?i)^best for\b", text):
            continue
        value = _normalize_skintype_text(text)
        types = _extract_skin_types_from_text(value)
        if types:
            return _format_skintype_list(types)

    return None


def extract_sephora_product_skintype(soup: BeautifulSoup) -> str:
    """
    Parse structured Skin Type lines in About the Product.
    Ignores concern highlights like Good for: Dryness.
    """
    root = _about_product_root(soup)
    if root:
        found = _extract_skintype_from_root(root)
        if found:
            return found

    blob = _page_product_json_blob(soup)
    json_value = _extract_labeled_field_from_json_blob(
        blob, ("skin type",), WHAT_IT_IS_JSON_FIELDS
    )
    if json_value:
        types = _extract_skin_types_from_text(_normalize_skintype_text(json_value))
        if types:
            return _format_skintype_list(types)

    return "N/A"


def extract_sephora_product_country(soup: BeautifulSoup) -> str:
    return "N/A"


def extract_sephora_product_capacity(soup: BeautifulSoup) -> str:
    """Default selected swatch (standard size) — ml when listed, else oz."""
    candidates: list[str] = []

    for button in soup.find_all("button", attrs={"data-at": "selected_swatch"}):
        candidates.append(button.get("aria-label", ""))
        for span in button.find_all("span"):
            candidates.append(span.get_text(" ", strip=True))

    for button in soup.find_all("button", attrs={"aria-label": True}):
        label = button.get("aria-label", "")
        if "ml" in label.lower() or "oz" in label.lower():
            candidates.append(label)

    for raw in candidates:
        capacity = _normalize_capacity(raw)
        if capacity:
            return capacity

    logger.warning("Capacity not found from selected swatch.")
    return "N/A"


def extract_sephora_product_price(soup: BeautifulSoup) -> str:
    """
    Sale price is the first <b> in the price span; second <b> is the original price.
    """
    price_el = soup.find(attrs={"data-at": "price"})
    if price_el:
        text = price_el.get_text(strip=True)
        if text:
            return text

    for span in soup.find_all("span"):
        bold_tags = span.find_all("b", recursive=False)
        if not bold_tags:
            continue
        for bold in bold_tags:
            text = bold.get_text(strip=True)
            if _PRICE_RE.match(text):
                return text

    match = re.search(r"\$\d+(?:\.\d{2})?", soup.get_text(" ", strip=True))
    if match:
        return match.group(0)

    logger.warning("Price not found.")
    return "N/A"


def extract_sephora_product_instructions(soup: BeautifulSoup) -> str:
    """
    From #how_to_use_section — prefer Suggested Usage, fall back to How to Use body.
    """
    roots = []
    section = _find_section_root(soup, "how_to_use_section")
    if section:
        roots.append(section)
    roots.append(soup)

    for root in roots:
        for label_tag in root.find_all(["strong", "b"]):
            label = label_tag.get_text(" ", strip=True).lower().rstrip(":")
            if label not in ("suggested usage", "how to use"):
                continue

            if label == "suggested usage":
                value = _value_after_label_tag(label_tag)
                if value:
                    return _normalize_instructions(value)

            parent = label_tag.parent
            if parent and parent.name == "p":
                next_list = parent.find_next_sibling("ul")
                if next_list:
                    steps = [
                        _normalize_instructions(li.get_text(" ", strip=True))
                        for li in next_list.find_all("li")
                        if li.get_text(strip=True)
                    ]
                    if steps:
                        return " ".join(steps)

            inline = _collect_text_after_heading(label_tag)
            if inline:
                return _normalize_instructions(inline)

    blob = _page_product_json_blob(soup)
    for field in ("suggestedUsage", "howToUse", "usage"):
        value = _extract_json_string_field(blob, field)
        if value:
            parsed = _instructions_from_html_fragment(value)
            if parsed:
                return parsed

    logger.warning("How to Use / Suggested Usage section not found.")
    return "N/A"


def extract_sephora_product_ingredients(soup: BeautifulSoup) -> str:
    """
    From #ingredients_section or #ingredients. Skip bullet callouts and disclaimers;
    return the comma-heavy INCI block (often after a double <br /> in one <div>).
    """
    section = _ingredients_section_root(soup)
    if section:
        parsed = _ingredients_from_root(section)
        if parsed:
            return parsed

        for label_tag in section.find_all(["strong", "b"]):
            label = label_tag.get_text(" ", strip=True).lower().rstrip(":")
            if label != "ingredients":
                continue
            container = label_tag.find_parent(["div", "section"]) or section
            parsed = _ingredients_from_root(container)
            if parsed:
                return parsed

    blob = _page_product_json_blob(soup)
    for field in INGREDIENT_JSON_FIELDS:
        value = _extract_json_string_field(blob, field)
        if value:
            parsed = _ingredients_from_html_fragment(value)
            if parsed:
                return parsed
            if _looks_like_ingredient_list(_html_fragment_to_text(value)):
                return _html_fragment_to_text(value)

    if not section:
        logger.warning("Ingredients section not found.")
    else:
        logger.warning("Ingredients list not found inside ingredients section.")
    return "N/A"


def extract_sephora_product_imageurls(soup: BeautifulSoup, limit: int = 4) -> list[str]:
    """
    Carousel product slides — prefer ProductImage buttons, fall back to SKU images.
    """
    seen: set[str] = set()
    images: list[str] = []

    def _add_image(src: str, *, enforce_min_width: bool = False) -> None:
        src = src.strip()
        if not src or "/productimages/sku/" not in src:
            return
        width_match = re.search(r"imwidth=(\d+)", src)
        if enforce_min_width and width_match and int(width_match.group(1)) < 200:
            return
        base = src.split("?", 1)[0]
        if base in seen:
            return
        seen.add(base)
        images.append(src)

    for button in soup.find_all(
        "button",
        attrs={"data-comp": lambda value: value and "ProductImage" in str(value)},
    ):
        for img in button.find_all("img", src=True):
            _add_image(img["src"])

    if not images:
        for img in soup.find_all("img", src=True):
            _add_image(img["src"], enforce_min_width=True)
            if len(images) >= limit: # Limit the number of images to 4
                return images

    if not images:
        logger.warning("No carousel product images found.")

    return images


def extract_sephora_product_rating(soup: BeautifulSoup) -> str:
    """
    Average rating from ReviewsStats — numeric span beside the star icon.
    Falls back to JSON-LD aggregateRating when reviews are below the fold.
    """
    reviews_root = soup.find(
        attrs={"data-comp": lambda value: value and "ReviewsStats" in str(value)}
    )
    search_roots = [reviews_root] if reviews_root else [soup]

    for root in search_roots:
        for star_img in root.find_all("img", src=lambda src: src and "star.svg" in src):
            parent = star_img.parent
            if not parent:
                continue
            for span in parent.find_all("span", recursive=False):
                text = span.get_text(strip=True)
                if _RATING_RE.match(text):
                    return _format_rating(text)

    for span in soup.find_all("span"):
        text = span.get_text(strip=True)
        if _RATING_RE.match(text):
            parent = span.parent
            if parent and parent.find("img", src=lambda src: src and "star.svg" in src):
                return _format_rating(text)

    json_ld_rating = _rating_from_json_ld(soup)
    if json_ld_rating:
        return json_ld_rating

    logger.warning("Rating not found.")
    return "N/A"
