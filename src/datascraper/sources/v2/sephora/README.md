# Sephora price refresh (v2)

This source fetches only the current price from the stored product URL. It skips product details, images, ingredients, ratings, and instructions. `SephoraPriceScraper` reuses the browser session for the batch; Sephora may still block automated requests.
