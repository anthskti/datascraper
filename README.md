# Product Data Scraper for Clearup 

This repository is a compliment to [Clearup.skin](https://www.clearup.skin)([repo](https://github.com/anthskti/ClearUp)).

Currently focuses on these retail stores:
1. [Yesstyle](yesstyle/README.md) — drawback: skin types are inconsistent.
2. [Sephora](sephora/README.md) — drawback: doesn't state country.

General Pipeline:

1. Playwright: handles interaction and navigation throughout website.
2. Beautiful Soup: handles getting the data.

Generally gets this product information line:
name,brand,category,labels,skinType,country,capacity,price,instructions,ingredients,imageUrls,averageRating,url,merchant,status

## Setup
Need python and uv (package manager) installed.
```bash
uv sync
```

Author: Anthony Pham
Created: February 17, 2026
Last Updated: July 22, 2026