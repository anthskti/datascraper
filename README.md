# Yesstyle Data Scraper

Pipeline:

1. Playwright ~ handles interaction and navigation throughout website.
2. Beautiful Soup ~ handles getting the data.

Playwright is good at not acting like a robot and can deal with anti-botting issues.
Beautiful Soup is good at precision and speed, not taking too many resources.

Yesstyle Query to Prompt

1. Format query into the search URL for yesstyle. "https://www.yesstyle.com/en/list.html?q="
2. Using Playwright, open chromium, and launch URL + query.
3. Using Beautiful Soup, use the html.parser and
4.

## Logistics

Virtual Environment

```bash
venv\Scripts\activate.bat
```
