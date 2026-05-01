import asyncio
import logging
import re
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup
from urllib.parse import quote

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Yesstyle have hashed HTML and CSS modules. Using Selectors as targets for attributes  
SELECTORS = {
    "price":        "span[class*='sellingPrice']",
    "brand_link":   "a.notranslate[href*='/list.html/bpt']",
    # "rating":       "aspan[class*='ratingStar']", # unsure, since it goes by width. jose of beauty is 85%
    # First product link on search results page
    "product_card": "a[href*='info.html/pid.']",
}

NAVIGATION_RETRIES = 2
NAVIGATION_TIMEOUT_MS = 30000
READY_TIMEOUT_MS = 12000

async def _goto_with_retries(page, url: str, ready_selector: str | None = None) -> bool:
    """
    Navigate with retries and wait for a key selector when provided.
    Returns True if navigation is likely ready for parsing.
    """
    for attempt in range(1, NAVIGATION_RETRIES + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            if ready_selector:
                await page.wait_for_selector(ready_selector, timeout=READY_TIMEOUT_MS)
            return True
        except PlaywrightTimeoutError:
            logger.warning(
                "Timeout loading %s (attempt %d/%d).",
                url,
                attempt,
                NAVIGATION_RETRIES,
            )
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

async def get_first_product_link(search_query: str) -> str | None:
    """
    Searches YesStyle and returns the URL of the first result. 
    """
    formatted_query = quote(search_query)
    search_url = (f"https://www.yesstyle.com/en/list.html?q={formatted_query}")
    # print(search_url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/119.0.0.0 Safari/537.36"        
        )
        page = await context.new_page()

        await _goto_with_retries(page, search_url, ready_selector=SELECTORS["product_card"])

        content = await page.content()
        await browser.close()

    soup = BeautifulSoup(content, 'html.parser')
    all_results = soup.select("a[class*='itemContainer'][href*='/info.html/pid.']")
    logger.info("Found %d product links", len(all_results))
    for i, r in enumerate(all_results[:5]):   # log first 5
        logger.info("  [%d] %s", i, r.get("href"))

    first_result = all_results[0] if all_results else None

    if first_result and first_result.get("href"):
        href = first_result["href"]
        return href if href.startswith("http") else f"https://www.yesstyle.com{href}"

    logger.error("No product card found. Selector may need updating: '%s'", SELECTORS["product_card"])
    return None

def _extract_images(soup: BeautifulSoup) -> list:
    """
    Pass 1 — Main thumbnail: identified by loading="eager" and a meaningful alt attribute
    Does Work ~ Pass 2 — Carousel:       identified by loading="lazy" and src containing /GalleryImage/
    Deduplicates and returns in order: [main] + [carousel...]
    """
    seen = set()
    images = []

    # Pass 1: Main thumbnail
    # Stable identifiers: loading="eager", fetchpriority="high", alt contains product name
    main = soup.find("img", {"loading": "eager", "fetchpriority": "high"})
    if main and main.get("src"):
        src = main["src"]
        seen.add(src)
        images.append(src)

    # Pass 2: Carousel images
    # Stable identifiers: loading="lazy", src path contains /GalleryImage/
    # for img in soup.find_all("img", {"loading": "lazy"}):
    #     src = img.get("src", "")
    #     if "/GalleryImage/" in src and src not in seen:
    #         seen.add(src)
    #         images.append(src)

    return images

def _extract_ingredients(soup: BeautifulSoup) -> str:
    """
    Ingredients live in a <span> with no attributes, inside a hashed class div.
    Strategy: find all role="region" divs, locate the one whose <span> text
    looks like an ingredient list (comma-separated, contains known cosmetic terms).
    """
    for region in soup.find_all("div", {"role": "region"}):
        # Find the accordion content div (partial class match)
        content_div = region.find("div", class_=lambda c: c and "accordionContent" in c)
        if not content_div:
            continue

        span = content_div.find("span")
        if not span:
            continue

        text = span.get_text(strip=True)

        # Ingredient lists are comma-separated and usually start with "Water"
        # This distinguishes them from other spans like disclaimers
        if text.count(",") > 5 and any(term in text for term in ["Water", "Glycerin", "Extract", "Acid"]):
            return text

    return "N/A"

def _extract_how_to_use(soup: BeautifulSoup) -> str:
    """
     Extracts "How to Use" steps from the product description accordion.
    """
    # Find every <b> tag whose text matches "how to use"
    for b_tag in soup.find_all("b"):
        if "how to use" not in b_tag.get_text(strip=True).lower():
            continue

        # Check if this <b> is wrapped in a <p>
        parent = b_tag.parent
        if parent and parent.name == "p":
            # The steps <ul> is the next sibling of the <p>
            next_ul = parent.find_next_sibling("ul")
            if next_ul:
                steps = [li.get_text(strip=True) for li in next_ul.find_all("li")]
                if steps:
                    return " ".join(steps)

    # <b> is inline with no wrapping <p>, collect <li> siblings after it
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

def _extract_rating(soup: BeautifulSoup) -> str:
    star_span = soup.find(
        "span",
        class_=lambda c: c and "ratingstar" in c and "colored" in c
    )

    if not star_span:
        logger.warning("Rating span not found. Selector may need updating.")
        return "N/A"

    style = star_span.get("style", "")  # e.g. "width:85px"

    # Parse the pixel value out of the inline style string
    match = re.search(r"width\s*:\s*(\d+(?:\.\d+)?)px", style)
    if not match:
        logger.warning("Could not parse width from style: '%s'", style)
        return "N/A"

    width_px = float(match.group(1))
    rating = round(width_px / 20, 2)    # convert to 0–5 scale
    return str(rating)

def _map_to_clearup_category(raw_category: str) -> str:
    category_map = {
        "cleanser": ["cleanser", "cleansing", "face cleansers"],
        "toner": ["toner"],
        "serum": ["face serums", "eye serums", "ampoule", "eye cream", "eye care"],
        "moisturizer": ["moisturizer", "cream", "lotion", "gel"],
        "sunscreen": ["sunscreen", "sun cream", "sunblock", "spf", "sun care"],
    }

    raw_lower = raw_category.lower()
    
    for target, keywords in category_map.items():
        if any(keyword in raw_lower for keyword in keywords):
            return target

    return "other"

def _extract_category(soup: BeautifulSoup) -> str:
    # Could also use this one.
    # <div class="productDetailPage-module-scss-module__dKBM_W__productInfoBox productDetailPage-module-scss-module__dKBM_W__shippingInfo"><h6>Bestseller Rank<span class="icon icon-angle-right"></span></h6><div class="productDetailPage-module-scss-module__dKBM_W__bestsellersRankWrapper"><span>#2 in <a href="/en/beauty-sunscreens/list.html/bcc.15601_bpt.46">Sunscreens</a></span><span>#4 in <a href="/en/beauty-beauty/list.html/bcc.15478_bpt.46">Beauty</a></span></div></div>

    breadcrumb_ul = soup.find("ul", class_=lambda c: c and "breadcrumbs" in c)
    if not breadcrumb_ul:
        return "N/A"
    
    items = [li.get_text(strip=True) for li in breadcrumb_ul.find_all("li")]
    
    categories = [i for i in items if i.lower() != "home"]

    # Some products only expose specific category names (e.g. "Eye Serums")
    # in deeper breadcrumb levels, so map across the full trail.
    for category in reversed(categories):
        mapped = _map_to_clearup_category(category)
        if mapped != "other":
            return mapped
    return "other"

def _extract_product_info_map(soup: BeautifulSoup) -> dict[str, str]:
    """
    Build a normalized map from the Product Information table.
    """
    info_map: dict[str, str] = {}
    rows = soup.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        label = cells[0].get_text(" ", strip=True).lower().rstrip(":")
        value = cells[1].get_text(" ", strip=True)
        if label and value:
            info_map[label] = value
    return info_map

def _extract_skintype(soup: BeautifulSoup) -> str:
    info_map = _extract_product_info_map(soup)
    if "recommended for" in info_map:
        return info_map["recommended for"]

    # Fallback for description format like:
    # <b>Skin types:</b> All skin types
    for b_tag in soup.find_all("b"):
        label = b_tag.get_text(" ", strip=True).lower().rstrip(":")
        if label in ("skin types", "skin type"):
            # First try immediate text sibling
            sibling = b_tag.next_sibling
            if isinstance(sibling, str):
                value = sibling.strip(" :\n\t")
                if value:
                    return value

            # Then try next text node in document order
            next_text = b_tag.find_next(string=True)
            if next_text:
                value = next_text.strip(" :\n\t")
                if value and value.lower() not in ("skin types", "skin type"):
                    return value

            # Finally try parent block text with label removed
            parent = b_tag.parent
            if parent:
                parent_text = parent.get_text(" ", strip=True)
                cleaned = re.sub(r"(?i)^skin types?\s*:\s*", "", parent_text).strip()
                if cleaned:
                    return cleaned

    return "N/A"

def _extract_country(soup: BeautifulSoup) -> str:
    info_map = _extract_product_info_map(soup)
    if "imported from" in info_map:
        return info_map["imported from"]
    return "N/A"

def _extract_capacity(soup: BeautifulSoup) -> str:
    info_map = _extract_product_info_map(soup)
    for key in ("volume", "size", "net wt", "capacity", "content"):
        if key in info_map:
            return info_map[key]

    # Fallback: option blocks often use labels like "Size:", "Capacity:", etc.
    for title in soup.select("span[class*='option-title']"):
        label = title.get_text(" ", strip=True).lower().rstrip(":")
        if label not in ("size", "volume", "capacity", "net wt", "content"):
            continue

        # Common pattern: <span class="option-title">Size:</span><span class="option-value">100ml</span>
        value_el = title.find_next_sibling("span")
        if value_el:
            value = value_el.get_text(" ", strip=True)
            if value:
                return value

        # If value is inline in the same parent text, remove the label.
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
    if match:
        return match.group(0)
    return "N/A"


async def scrape_yesstyle_product(url: str) -> dict:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/119.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        ready = await _goto_with_retries(
            page,
            url,
            ready_selector="span[class*='sellingPrice'], ul[class*='breadcrumbs'], div[role='region']",
        )
        if not ready:
            logger.warning("Product page may be partially loaded; parsing with fallback extraction.")

        content = await page.content()
        await browser.close()

    soup = BeautifulSoup(content, 'html.parser')
    data = {
        "price":      "N/A",
        "rating":     "N/A",
        "images":     [],
        "how_to_use": "N/A",
        "ingredients":"N/A",
        "category":   "N/A",
        "skinType":   "N/A",
        "country":    "N/A",
        "capacity":   "N/A",
    }

    # Price
    price_el = soup.select_one(SELECTORS["price"])
    if price_el:
        data["price"] = price_el.get_text(" ", strip=True)
    
    # Rating
    data["rating"] = _extract_rating(soup)

    # Images
    data["images"] = _extract_images(soup)

    # how to use
    data["how_to_use"] = _extract_how_to_use(soup)

    # Ingredients
    data["ingredients"] = _extract_ingredients(soup)

    # Category
    data["category"] = _extract_category(soup)

    # Skin Type
    data["skinType"] = _extract_skintype(soup)

    # Country
    data["country"] = _extract_country(soup)

    # Capacity
    data["capacity"] = _extract_capacity(soup)

    return data


# Entry point 
async def main():
    product_name = "Beauty of Joseon Revive Eye Serum"
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