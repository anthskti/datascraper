"""
Category, label, and skin-type rules for Clearup product taxonomy.
Pure rules + soup-backed resolvers; DOM helpers live in yesstyle_extractors.
"""

import re
from bs4 import BeautifulSoup

from yesstyle_extractors import (
    extract_product_info_map,
    extract_product_name,
    marketing_search_roots,
)

# ── Taxonomy (category, labels, skin types) ───────────────────────────────────

ALL_SKIN_TYPES = [
    "oily",
    "dry",
    "combination",
    "sensitive",
    "normal",
    "acne-prone",
]

# Placeholder when a fixed label slot has no match (multi-slot categories only).
LABEL_NA = "-"

# First match wins (single-label categories).
TONER_BENEFIT_PRIORITY = ("exfoliating", "hydrating", "calming", "balancing")
ESSENCE_EFFECT_PRIORITY = ("hydrating", "calming", "brightening")
CLEANSER_TEXTURE_PRIORITY = ("oil", "balm", "foam", "gel", "milk")
MOISTURIZER_TEXTURE_PRIORITY = ("gel", "cream", "ointment", "lotion", "emulsion")
MOISTURIZER_FINISH_PRIORITY = ("matte", "natural", "dewy", "glassy")

# Max length for a skin-type snippet (longer text is marketing copy, not a skin field).
_MAX_SKINTYPE_SNIPPET_LEN = 80

# Checked in order; first match wins. Longer phrases must come before shorter ones.
# Tuples since read only.
NAME_CATEGORY_PHRASES: list[tuple[str, tuple[str, ...]]] = [
    ("sunscreen", ("sunscreen", "sun cream", "sunblock", "sun stick", "sun gel", "sun fluid", "uv cream", "sun")),
    (
        "cleanser",
        (
            "cleansing oil",
            "cleansing balm",
            "cleansing milk",
            "cleansing foam",
            "cleansing water",
            "cleansing gel",
            "foam cleanser",
            "face wash",
            "cleanser",
        ),
    ),
    ("essence", ("facial spray", "face mist", "facial mist", "mist", "essence")),
    ("toner", ("toner",)),
    ("serum", ("ampoule", "serum", "booster")),
    (
        "moisturizer",
        (
            "moisturizer",
            "moisturiser",
            "water gel",
            "gel cream",
            "sleeping mask",
            "night cream",
            "day cream",
            "eye cream",
            "cream",
            "lotion",
            "emulsion",
            "ointment",
        ),
    ),
]

BREADCRUMB_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cleanser": ("cleanser", "cleansing", "face cleansers"),
    "toner": ("toner", "exfoliator", "exfoliators"),
    "essence": ("mist & essence","face mist", "face mists", "facial mist", "setting spray"),
    "serum": ("face serums", "eye serums", "ampoule", "eye care"),
    "moisturizer": ("moisturizer", "cream", "lotion", "gel", "emulsion"),
    "sunscreen": ("sunscreen", "sun cream", "sunblock", "spf", "sun care"),
}

CLEANSER_TEXTURE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "oil": ("cleansing oil", " cleansing oil", " oil cleanser", " oil "), # Spaces are for whole word. ex "oil-free" when "oil" fails.
    "balm": ("cleansing balm", " balm "),
    "gel": ("cleansing gel", " gel cleanser"),
    "foam": ("foam cleanser", "cleansing foam", " foam "),
    "milk": ("cleansing milk", " milk cleanser"),
}

TONER_BENEFIT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hydrating": ("hydrating", "hydration", "hydrates", "hydrate", "moisturizing toner"),
    "exfoliating": (
        "exfoliating",
        "exfoliation",
        "aha",
        "bha",
        "pha",
        "protease",
        "salicylic",
        "lactic acid",
        "glycolic",
    ),
    "calming": ("calming", "soothing", "cica", "centella"),
    "balancing": ("balancing", "balance", "ph balancing"),
}

ESSENCE_EFFECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hydrating": ("hydrating", "hydration", "hydrates", "hydrate", "moisturizing"),
    "calming": ("calming", "soothing", "cica", "centella", "mugwort"),
    "brightening": ("brightening", "brighten", "glow", "niacinamide", "vitamin c"),
}

SERUM_ACTIVE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "vitamin c": ("vitamin c", "ascorbic"),
    "hyaluronic acid": ("hyaluronic", "sodium hyaluronate"),
    "niacinamide": ("niacinamide","niacin"),
    "retinol": ("retinol",),
    "retinal": ("retinal",),
    "aha": (" aha", "aha,", "glycolic", "lactic acid"),
    "bha": (" bha", "bha,", "salicylic"),
    "peptides": ("peptide",),
    "azelaic acid": ("azelaic",),
    "tranexamic acid": ("tranexamic",),
    "ceramides": ("ceramide",),
}

SERUM_CONCENTRATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "serum": (" serum", "serum "),
    "ampoule": ("ampoule",),
    "booster": ("booster",),
}


SERUM_ACTIVE_PRIORITY = tuple(SERUM_ACTIVE_KEYWORDS.keys())
SERUM_CONCENTRATION_PRIORITY = ("ampoule", "serum", "booster")

MOISTURIZER_TEXTURE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "gel": (" gel", "gel ", "water gel", "gel cream"),
    "cream": ("cream",),
    "ointment": ("ointment",),
    "lotion": ("lotion",),
    "emulsion": ("emulsion",),
}

MOISTURIZER_FINISH_KEYWORDS: dict[str, tuple[str, ...]] = {
    "matte": ("matte", "invisible", "weightless"),
    "natural": ("natural", "natural finish", "natural-looking"),
    "dewy": ("dewy", "glowy"),
    "glassy": ("glassy", "glass skin", "healthy glow"),
}

# "What it is" description hints when explicit finish terms are absent.
DESCRIPTION_FINISH_HINTS: dict[str, tuple[str, ...]] = {
    "dewy": ("hydrating", "hydration", "hydrates", "hydrate"),
    "glassy": ("smooth", "glass skin", "healthy glow"),
    "matte": ("invisible", "matte", "weightless"),
}

SUNSCREEN_SPF_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("50+", ("spf 50", "spf50", "spf 50+", "pa++++")),
    ("30+", ("spf 30", "spf30", "spf 40")),
    ("15+", ("spf 15", "spf25", "spf 25")),
)

SUNSCREEN_FINISH_KEYWORDS = MOISTURIZER_FINISH_KEYWORDS

MINERAL_FILTER_MARKERS = ("zinc oxide", "titanium dioxide")
CHEMICAL_FILTER_MARKERS = (
    "ethylhexyl",
    "homosalate",
    "octinoxate",
    "avobenzone",
    "diethylamino",
    "methylene bis-benzotriazolyl",
    "octocrylene",
)
def _normalize_lookup_text(*parts: str) -> str:
    return " ".join(p.strip().lower() for p in parts if p and p.strip())


# Helper function to check if any keyword is in the text.
def _text_has_any(text: str, keywords: tuple[str, ...]) -> bool: # Since our tuple can contain any number of strings, [str, ...]
    return any(keyword in text for keyword in keywords)


# Iterate through all tuples in NAME_CATEGORY_PHRASES and check if the product name contains any of the phrases.
def _extract_category_from_name(product_name: str) -> str | None:
    name_lower = product_name.lower()
    for category, phrases in NAME_CATEGORY_PHRASES:
        if any(phrase in name_lower for phrase in phrases):
            return category
    return None

# BACK UP: checks breadcrumbs for category if "_extract_category_from_name" fails.
def _map_breadcrumb_to_category(raw_category: str) -> str:
    raw_lower = raw_category.lower()
    for target, keywords in BREADCRUMB_CATEGORY_KEYWORDS.items():
        if any(keyword in raw_lower for keyword in keywords):
            return target
    return "other"

def _extract_category_from_breadcrumbs(soup: BeautifulSoup) -> str:
    breadcrumb_ul = soup.find("ul", class_=lambda c: c and "breadcrumbs" in c)
    if not breadcrumb_ul:
        return "other"

    items = [li.get_text(strip=True) for li in breadcrumb_ul.find_all("li")]
    categories = [item for item in items if item.lower() != "home"]

    for category in reversed(categories):
        mapped = _map_breadcrumb_to_category(category)
        if mapped != "other":
            return mapped
    return "other"


def extract_category(
    soup: BeautifulSoup, product_name: str | None = None
) -> str:
    """Figures out the category from product name first, then YesStyle breadcrumbs."""
    name = (product_name or "").strip() or extract_product_name(soup)
    if name:
        from_name = _extract_category_from_name(name)
        if from_name:
            return from_name
    return _extract_category_from_breadcrumbs(soup)




def _extract_skin_types_from_text(text: str) -> list[str]:
    found: list[str] = []
    normalized = text.lower().replace("/", " ").replace("&", " and ")

    if "acne prone" in normalized or "acne-prone" in normalized:
        found.append("acne-prone")
    if re.search(r"\bsensitive\b", normalized):
        found.append("sensitive")
    if re.search(r"\bcombination\b", normalized):
        found.append("combination")
    if re.search(r"\boily\b", normalized):
        found.append("oily")
    if re.search(r"\bdry\b", normalized):
        found.append("dry")
    if re.search(r"\bnormal\b", normalized):
        found.append("normal")

    return [skin for skin in ALL_SKIN_TYPES if skin in found]


def _is_all_skin_types_text(text: str) -> bool:
    lower = text.lower()
    return "all skin type" in lower or "all skin types" in lower


def _format_skin_types(types: list[str]) -> str:
    if not types:
        return "N/A"
    return ", ".join(types)


def _looks_like_skintype_snippet(raw: str) -> bool:
    """Reject editor notes / feature paragraphs mistaken for skin-type fields."""
    text = raw.strip()
    if not text or text.upper() == "N/A":
        return False
    if len(text) > _MAX_SKINTYPE_SNIPPET_LEN:
        return False
    if len(text.split()) > 12:
        return False
    lower = text.lower()
    if "editor" in lower and "note" in lower:
        return False
    if _is_all_skin_types_text(text):
        return True
    if _extract_skin_types_from_text(text):
        return True
    # Short "Recommended for: oily skin" style lines
    if re.search(r"\b(skin type|recommended for|suitable for)\b", lower):
        return True
    return False


def _resolve_skin_types_from_raw(raw: str) -> str | None:
    if not raw or not _looks_like_skintype_snippet(raw):
        return None

    if _is_all_skin_types_text(raw):
        # "All skin types, especially dry and sensitive" → all types for the DB
        return _format_skin_types(ALL_SKIN_TYPES)

    specific = _extract_skin_types_from_text(raw)
    if specific:
        return _format_skin_types(specific)

    return None


def _skintype_value_after_b_tag(b_tag) -> str | None:
    sibling = b_tag.next_sibling
    if isinstance(sibling, str):
        value = sibling.strip(" :\n\t")
        if value:
            return value
    parent = b_tag.parent
    if parent:
        parent_text = parent.get_text(" ", strip=True)
        label = b_tag.get_text(" ", strip=True).lower().rstrip(":")
        cleaned = re.sub(
            rf"(?i)^{re.escape(label)}\s*:?\s*",
            "",
            parent_text,
        ).strip()
        if cleaned:
            return cleaned
    return None


def _split_skintype_prose_lines(text: str) -> list[str]:
    """Split marketing copy into sentence-sized chunks for safe skin-type mining."""
    normalized = re.sub(r"\s+", " ", text.strip())
    if not normalized:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalized) if part.strip()]


def _is_editor_note_root(root) -> bool:
    return bool(
        root.find("h6", class_=lambda c: c and "editor" in str(c).lower())
    )


def _append_unique_snippet(snippets: list[str], value: str | None) -> None:
    if not value:
        return
    cleaned = value.strip()
    if cleaned and cleaned not in snippets:
        snippets.append(cleaned)


def _extract_structured_skintype_snippets(soup: BeautifulSoup) -> list[str]:
    """
    Formal skin-type fields: product table, <b>Skin types:</b>, Recommended for blocks.
    """
    snippets: list[str] = []

    info_map = extract_product_info_map(soup)
    if "recommended for" in info_map:
        _append_unique_snippet(snippets, info_map["recommended for"])

    search_roots = list(marketing_search_roots(soup))
    search_roots.append(soup)

    seen_root_ids: set[int] = set()
    for root in search_roots:
        root_id = id(root)
        if root_id in seen_root_ids:
            continue
        seen_root_ids.add(root_id)

        for b_tag in root.find_all("b"):
            label = b_tag.get_text(" ", strip=True).lower().rstrip(":")
            if label in ("skin types", "skin type"):
                _append_unique_snippet(snippets, _skintype_value_after_b_tag(b_tag))

        for tag in root.find_all(["b", "strong"]):
            label = tag.get_text(" ", strip=True).lower().rstrip(":")
            if label != "recommended for":
                continue
            container = tag.find_parent(["ul", "li", "p", "div"]) or tag.parent
            if not container:
                continue
            for inner in container.find_all("b"):
                inner_label = inner.get_text(" ", strip=True).lower().rstrip(":")
                if inner_label in ("skin types", "skin type"):
                    _append_unique_snippet(snippets, _skintype_value_after_b_tag(inner))

    return snippets


def _iter_editor_skintype_lines(soup: BeautifulSoup):
    """Editor's Note: one sentence at a time (e.g. Suitable for acne-prone skin)."""
    for root in marketing_search_roots(soup):
        if not _is_editor_note_root(root):
            continue
        section = root.find("section") or root
        text = section.get_text(" ", strip=True)
        text = re.sub(r"(?i)^editor'?s?\s+note\s*:?\s*", "", text).strip()
        for sentence in _split_skintype_prose_lines(text):
            yield sentence
        break


def _iter_benefits_skintype_lines(soup: BeautifulSoup):
    """Features / Benefits bullets (e.g. suitable for acne-prone skin in <li>)."""
    for b_tag in soup.find_all("b"):
        label = b_tag.get_text(" ", strip=True).lower().rstrip(":")
        if "benefit" not in label:
            continue
        container = b_tag.find_parent("div") or b_tag.parent
        if not container:
            continue
        for li in container.find_all("li"):
            line = li.get_text(" ", strip=True)
            if line:
                yield line
        break


def _collect_skin_types_from_snippets(snippets: list[str]) -> list[str]:
    merged: list[str] = []
    for snippet in snippets:
        resolved = _resolve_skin_types_from_raw(snippet)
        if not resolved:
            continue
        for skin in resolved.split(", "):
            if skin and skin not in merged:
                merged.append(skin)
    return merged


def _extract_sunscreen_spf_labels(text: str) -> list[str]:
    for label, patterns in SUNSCREEN_SPF_PATTERNS:
        if _text_has_any(text, patterns):
            return [label]
    match = re.search(r"\bspf\s*(\d{2})\b", text)
    if match:
        value = int(match.group(1))
        if value >= 50:
            return ["50+"]
        if value >= 30:
            return ["30+"]
        if value >= 15:
            return ["15+"]
    return []


def _extract_sunscreen_filter_label(text: str, ingredients: str) -> str | None:
    combined = _normalize_lookup_text(text, ingredients)
    has_mineral = _text_has_any(combined, MINERAL_FILTER_MARKERS)
    has_chemical = _text_has_any(combined, CHEMICAL_FILTER_MARKERS)
    if has_mineral and has_chemical:
        return "hybrid"
    if has_mineral:
        return "mineral"
    if has_chemical:
        return "chemical"
    if "mineral sunscreen" in combined:
        return "mineral"
    if "chemical sunscreen" in combined:
        return "chemical"
    if "hybrid" in combined:
        return "hybrid"
    return None


def _pick_first_keyword_label(
    text: str,
    keyword_map: dict[str, tuple[str, ...]],
    priority: tuple[str, ...],
) -> str | None:
    for label in priority:
        if _text_has_any(text, keyword_map[label]):
            return label
    return None


def _pick_cleanser_texture_from_formulation(formulation: str) -> str | None:
    """Fallback: Sephora Formulation line often says Gel, Foam, etc. on its own."""
    lower = formulation.lower()
    for label in CLEANSER_TEXTURE_PRIORITY:
        if re.search(rf"\b{re.escape(label)}\b", lower):
            return label
    return None


def _pick_cleanser_texture(
    product_name: str, text: str, formulation_text: str | None = None
) -> str | None:
    name_lower = product_name.lower()
    for label in CLEANSER_TEXTURE_PRIORITY:
        if _text_has_any(name_lower, CLEANSER_TEXTURE_KEYWORDS[label]):
            return label
    hit = _pick_first_keyword_label(text, CLEANSER_TEXTURE_KEYWORDS, CLEANSER_TEXTURE_PRIORITY)
    if hit:
        return hit
    if formulation_text:
        return _pick_cleanser_texture_from_formulation(formulation_text)
    return None


def _pick_moisturizer_texture(product_name: str, text: str) -> str:
    name_lower = product_name.lower()
    for label in MOISTURIZER_TEXTURE_PRIORITY:
        if label in name_lower:
            return label
    hit = _pick_first_keyword_label(
        text, MOISTURIZER_TEXTURE_KEYWORDS, MOISTURIZER_TEXTURE_PRIORITY
    )
    return hit or LABEL_NA


def _pick_toner_format(product_name: str) -> str:
    if re.search(r"\bpads?\b", product_name, flags=re.IGNORECASE):
        return "toner pad"
    return "liquid toner"


def _pick_label_from_text(
    description_text: str,
    full_text: str,
    keyword_map: dict[str, tuple[str, ...]],
    priority: tuple[str, ...],
) -> str | None:
    """Prefer About-the-Product copy, then fall back to the wider lookup text."""
    return _pick_first_keyword_label(
        description_text, keyword_map, priority
    ) or _pick_first_keyword_label(full_text, keyword_map, priority)


def _pick_moisturizer_finish(description_text: str, full_text: str) -> str:
    hit = _pick_first_keyword_label(
        full_text, MOISTURIZER_FINISH_KEYWORDS, MOISTURIZER_FINISH_PRIORITY
    )
    if hit:
        return hit

    for label in MOISTURIZER_FINISH_PRIORITY:
        if _text_has_any(description_text, DESCRIPTION_FINISH_HINTS.get(label, ())):
            return label

    return LABEL_NA


def _format_label_slots(slots: list[str]) -> str:
    return ",".join(slots)


def extract_labels(
    category: str,
    product_name: str,
    marketing_text: str,
    ingredients: str,
    description_text: str | None = None,
    formulation_text: str | None = None,
) -> str:
    text = _normalize_lookup_text(product_name, marketing_text, ingredients)
    desc = _normalize_lookup_text(description_text or marketing_text)

    if category == "cleanser":
        hit = _pick_cleanser_texture(product_name, text, formulation_text=formulation_text)
        return hit or ""

    elif category == "toner":
        benefit = _pick_label_from_text(
            desc, text, TONER_BENEFIT_KEYWORDS, TONER_BENEFIT_PRIORITY
        )
        return _format_label_slots([benefit or LABEL_NA, _pick_toner_format(product_name)])

    elif category == "essence":
        hit = _pick_label_from_text(
            desc, text, ESSENCE_EFFECT_KEYWORDS, ESSENCE_EFFECT_PRIORITY
        )
        return hit or ""

    elif category == "serum":
        active = _pick_first_keyword_label(
            text, SERUM_ACTIVE_KEYWORDS, SERUM_ACTIVE_PRIORITY
        )
        concentration = _pick_first_keyword_label(
            text, SERUM_CONCENTRATION_KEYWORDS, SERUM_CONCENTRATION_PRIORITY
        )
        return _format_label_slots([active or LABEL_NA, concentration or LABEL_NA])

    elif category == "moisturizer":
        texture = _pick_moisturizer_texture(product_name, text)
        finish = _pick_moisturizer_finish(desc, text)
        return _format_label_slots([texture, finish])

    elif category == "sunscreen":
        spf = (_extract_sunscreen_spf_labels(text) or [LABEL_NA])[0]
        finish = _pick_moisturizer_finish(desc, text)
        filter_label = _extract_sunscreen_filter_label(text, ingredients) or LABEL_NA
        return _format_label_slots([spf, finish, filter_label])

    return ""


def extract_skintype(soup: BeautifulSoup) -> str:
    """
    1. Structured fields (product table, <b>Skin types:</b>, Recommended for blocks)
    2. Editor's Note — one sentence at a time
    3. Features / Benefits list items
    4. N/A if nothing resolves to a canonical skin type
    """
    snippets: list[str] = []
    snippets.extend(_extract_structured_skintype_snippets(soup))

    for line in _iter_editor_skintype_lines(soup):
        _append_unique_snippet(snippets, line)

    for line in _iter_benefits_skintype_lines(soup):
        _append_unique_snippet(snippets, line)

    types = _collect_skin_types_from_snippets(snippets)
    return _format_skin_types(types) if types else "N/A"
