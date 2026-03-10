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

        try:
            await page.goto(search_url, wait_until="networkidle", timeout=30000) # 30 seconds 
        except PlaywrightTimeoutError:
            logger.warning("Searching page timed out while getting first product link.")

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
        "cleanser":   "face cleansers",
        "toner":      "toners",
        # "essence":    ["essence", "treatment"], essence end up being serums
        "serum":      "face serums", 
        "moisturizer":"moisturizers",
        "sunscreen":  "sunscreens",
    }

    raw_lower = raw_category.lower()
    
    for target, keywords in category_map.items():
        if (raw_lower in keywords):
            return target

    return "other"

async def _extract_category(soup: BeautifulSoup) -> str:
    # Could also use this one.
    # <div class="productDetailPage-module-scss-module__dKBM_W__productInfoBox productDetailPage-module-scss-module__dKBM_W__shippingInfo"><h6>Bestseller Rank<span class="icon icon-angle-right"></span></h6><div class="productDetailPage-module-scss-module__dKBM_W__bestsellersRankWrapper"><span>#2 in <a href="/en/beauty-sunscreens/list.html/bcc.15601_bpt.46">Sunscreens</a></span><span>#4 in <a href="/en/beauty-beauty/list.html/bcc.15478_bpt.46">Beauty</a></span></div></div>

    breadcrumb_ul = soup.find("ul", class_=lambda c: c and "breadcrumbs" in c)
    if not breadcrumb_ul:
        return "N/A"
    
    items = [li.get_text(strip=True) for li in breadcrumb_ul.find_all("li")]
    
    categories = [i for i in items if i.lower() != "home"]

    if len(categories) >= 2:
        return _map_to_clearup_category(categories[2])
    return "other"

async def _extract_skintype(soup: BeautifulSoup) -> str:
    # TODO
    return

async def _extract_country(soup: BeautifulSoup) -> str:
    label_td = soup.find("td", string=lambda s: s and "Imported from:" in s)

    if label_td:
        value_td=label_td.find_nextsibling("td")
        if value_td:
            return value_td.get_text(strip=True)
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
        
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000) # 30 seconds
        except PlaywrightTimeoutError:
            logger.warning("Product page timed out while parsing the content.")

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
        "country":    "N/A"
    }

    # Price
    data["price"] = soup.select_one(SELECTORS["price"])
    
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

    # Country
    data["country"] = _extract_country(soup)
    

    return data


# Entry point 
async def main():
    product_name = "SKIN1004 Madagascar Centella Asiatica 100 Ampoule"
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