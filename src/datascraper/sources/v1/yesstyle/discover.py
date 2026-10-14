"""Discover YesStyle product URLs from brand listing pages with Apify."""

import csv
import json
import logging
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

APIFY_API = "https://api.apify.com/v2"
ACTOR_ID = "apify~website-content-crawler"
DATASET_PAGE_SIZE = 250
PRODUCT_PATH_RE = re.compile(r"/info\.html/pid\.(\d+)", re.IGNORECASE)
YESSTYLE_HOSTS = {"yesstyle.com", "www.yesstyle.com"}


def _host_is_yesstyle(host: str) -> bool:
    normalized = host.casefold().rstrip(".")
    return normalized in YESSTYLE_HOSTS or normalized.endswith(".yesstyle.com")


def _canonical_product_url(raw_url: str) -> str | None:
    try:
        parts = urlsplit(raw_url.strip())
    except ValueError:
        return None
    if parts.scheme.casefold() not in {"http", "https"} or not _host_is_yesstyle(
        parts.hostname or ""
    ):
        return None
    if not PRODUCT_PATH_RE.search(parts.path):
        return None
    # YesStyle product IDs identify the page; drop tracking query strings and fragments.
    return urlunsplit(("https", (parts.hostname or "").casefold(), parts.path, "", ""))


def _read_brand_seeds(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Brand seed CSV not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("Brand seed CSV must have a header row")
        headers = {header.strip().casefold(): header for header in reader.fieldnames}
        brand_column = headers.get("brand")
        listing_column = headers.get("listingurl") or headers.get("url")
        if not brand_column or not listing_column:
            raise ValueError("Brand seed CSV needs columns: brand,listingUrl")

        seeds: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            brand = (row.get(brand_column) or "").strip()
            listing_url = (row.get(listing_column) or "").strip()
            if not brand or not listing_url:
                logger.warning("Skipping incomplete brand seed at row %d", row_number)
                continue
            parts = urlsplit(listing_url)
            if parts.scheme.casefold() not in {"http", "https"} or not _host_is_yesstyle(
                parts.hostname or ""
            ):
                raise ValueError(
                    f"Row {row_number} is not a valid YesStyle listing URL: {listing_url}"
                )
            seeds.append({"brand": brand, "listing_url": listing_url})
    if not seeds:
        raise ValueError("Brand seed CSV has no usable rows")
    return seeds


def _api_json(url: str, token: str, *, method: str = "GET", payload: dict | None = None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Apify API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the Apify API: {exc.reason}") from exc


def _api_data(response: dict) -> dict:
    """Unwrap the standard Apify API response envelope."""
    data = response.get("data")
    return data if isinstance(data, dict) else response


def _brand_listing_glob(listing_url: str) -> str:
    parts = urlsplit(listing_url)
    return f"https://{parts.netloc}{parts.path}*"


def _product_page_globs(listing_url: str) -> list[dict[str, str]]:
    host = (urlsplit(listing_url).hostname or "www.yesstyle.com").casefold()
    hosts = {host, "www.yesstyle.com", "yesstyle.com"}
    return [
        {"glob": f"https://{product_host}/**/info.html/pid.**"}
        for product_host in sorted(hosts)
    ]


def _run_actor(
    listing_url: str,
    *,
    token: str,
    max_pages: int,
    max_depth: int,
    wait_timeout: float,
) -> tuple[str, str]:
    input_data = {
        "startUrls": [{"url": listing_url}],
        "crawlerType": "playwright:adaptive",
        "useSitemaps": False,
        "respectRobotsTxtFile": True,
        "maxCrawlPages": max_pages,
        "maxCrawlDepth": max_depth,
        "maxConcurrency": 2,
        "includeUrlGlobs": [{"glob": _brand_listing_glob(listing_url)}]
        + _product_page_globs(listing_url),
    }
    run = _api_data(_api_json(
        f"{APIFY_API}/acts/{quote(ACTOR_ID, safe='~')}/runs",
        token,
        method="POST",
        payload=input_data,
    ))
    run_id = run.get("id")
    if not run_id:
        raise RuntimeError("Apify did not return a run ID")

    deadline = time.monotonic() + wait_timeout
    while True:
        status = run.get("status")
        if status in {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}:
            break
        if time.monotonic() >= deadline:
            partial_dataset = run.get("defaultDatasetId")
            raise TimeoutError(
                f"Apify run {run_id} exceeded the wait timeout; "
                f"datasetId={partial_dataset or 'not available'}"
            )
        time.sleep(5)
        run = _api_data(_api_json(f"{APIFY_API}/actor-runs/{quote(run_id, safe='')}", token))

    if run.get("status") != "SUCCEEDED":
        raise RuntimeError(f"Apify run {run_id} ended with status {run.get('status')}")
    dataset_id = run.get("defaultDatasetId")
    if not dataset_id:
        raise RuntimeError(f"Apify run {run_id} has no output dataset")
    return run_id, dataset_id


def _read_dataset(dataset_id: str, token: str) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        query = urlencode(
            {"format": "json", "clean": "true", "offset": offset, "limit": DATASET_PAGE_SIZE}
        )
        batch = _api_json(
            f"{APIFY_API}/datasets/{quote(dataset_id, safe='')}/items?{query}", token
        )
        if not isinstance(batch, list):
            raise RuntimeError(f"Apify dataset {dataset_id} did not return a JSON array")
        items.extend(item for item in batch if isinstance(item, dict))
        if len(batch) < DATASET_PAGE_SIZE:
            return items
        offset += len(batch)


def _brand_file_slug(brand: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", brand.casefold()).strip("-")
    return slug or "brand"


def discover_yesstyle_urls(
    input_csv: Path,
    output_csv: Path,
    *,
    max_pages: int,
    max_depth: int = 3,
    dataset_id: str | None = None,
    wait_timeout: float = 3600,
    artifact_dir: Path,
) -> int:
    """Crawl YesStyle brand pages and write deduplicated brand/product URL pairs."""
    if max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if max_depth < 0:
        raise ValueError("max_depth cannot be negative")

    seeds = _read_brand_seeds(input_csv)
    if dataset_id and len(seeds) != 1:
        raise ValueError("--dataset-id can be used with exactly one brand seed row")
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        raise RuntimeError("APIFY_TOKEN is not set")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    output_rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for index, seed in enumerate(seeds, start=1):
        brand = seed["brand"]
        if dataset_id:
            run_id = "reused"
            current_dataset_id = dataset_id
        else:
            logger.info("Starting Apify crawl %d/%d for %s", index, len(seeds), brand)
            run_id, current_dataset_id = _run_actor(
                seed["listing_url"],
                token=token,
                max_pages=max_pages,
                max_depth=max_depth,
                wait_timeout=wait_timeout,
            )

        items = _read_dataset(current_dataset_id, token)
        manifest_path = artifact_dir / f"{_brand_file_slug(brand)}_{run_id}_manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "brand": brand,
                    "listingUrl": seed["listing_url"],
                    "runId": run_id,
                    "datasetId": current_dataset_id,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        logger.info("Read %d Apify pages for %s", len(items), brand)

        brand_urls: set[str] = set()
        for item in items:
            page_url = item.get("url") or item.get("loadedUrl")
            if not isinstance(page_url, str):
                continue
            canonical_url = _canonical_product_url(page_url)
            if canonical_url:
                brand_urls.add(canonical_url)

        if not brand_urls:
            logger.warning("No YesStyle product URLs found for %s", brand)
        for url in sorted(brand_urls):
            key = url.casefold()
            if key in seen:
                continue
            seen.add(key)
            output_rows.append({"brand": brand, "url": url})

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["brand", "url"])
        writer.writeheader()
        writer.writerows(output_rows)

    logger.info("Wrote %d unique product URLs to %s", len(output_rows), output_csv)
    return len(output_rows)
