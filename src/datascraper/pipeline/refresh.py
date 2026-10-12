"""Refresh merchant prices from the URLs stored in Clearup."""

import asyncio
import csv
import logging
from collections import Counter, defaultdict
from pathlib import Path

from datascraper.storage.postgres import fetch_product_merchants

logger = logging.getLogger(__name__)

REFRESH_FIELDS = ["brand", "name", "price", "merchant"]
MERCHANT_ALIASES = {
    "yesstyle": "yesstyle",
    "sephora": "sephora",
}


def _identity(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        row.get("brand", "").strip().casefold(),
        row.get("name", "").strip().casefold(),
        row.get("merchant", "").strip().casefold(),
    )


def _usable_price(value: object) -> str | None:
    price = " ".join(str(value or "").split())
    if not price or price.casefold() in {"n/a", "na", "none", "null", "-"}:
        return None
    return price


async def _refresh_row(
    row: dict[str, str], scraper, semaphore: asyncio.Semaphore, delay: float
) -> tuple[str, dict[str, str] | None]:
    async with semaphore:
        merchant = row["merchant"].strip()
        try:
            price = _usable_price(await scraper.scrape_price(row["url"]))
            if price is None:
                logger.warning("No usable price for listing %s", row["product_merchant_id"])
                return "failed", None

            return "processed", {
                "brand": row["brand"],
                "name": row["name"],
                "price": price,
                "merchant": merchant,
            }
        except Exception as exc:
            logger.error(
                "Refresh failed for listing %s (%s): %s",
                row["product_merchant_id"],
                merchant,
                exc,
            )
            return "failed", None
        finally:
            await asyncio.sleep(delay)


async def _refresh_merchant_rows(
    source: str,
    rows: list[dict[str, str]],
    max_workers: int,
    delay: float,
) -> list[tuple[str, dict[str, str] | None]]:
    if source == "yesstyle":
        from datascraper.sources.v2.yesstyle.scraper import YesStylePriceScraper

        scraper_type = YesStylePriceScraper
    else:
        from datascraper.sources.v2.sephora.scraper import SephoraPriceScraper

        scraper_type = SephoraPriceScraper

    semaphore = asyncio.Semaphore(max(1, max_workers))
    try:
        async with scraper_type() as scraper:
            return await asyncio.gather(
                *(
                    _refresh_row(row, scraper, semaphore, delay)
                    for row in rows
                )
            )
    except Exception as exc:
        logger.error("Could not start %s price refresh session: %s", source, exc)
        return [("failed", None) for _ in rows]


async def refresh_prices(
    output_csv: Path,
    limit: int | None = None,
    max_workers: int = 1,
    delay_between_requests: float = 5.0,
) -> Counter[str]:
    """Read candidates, refresh their prices, and write successful rows only."""
    candidates = fetch_product_merchants(limit=limit)
    logger.info("Loaded %d product-merchant rows from Clearup", len(candidates))

    identities: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        identities[_identity(row)].append(row)

    counts: Counter[str] = Counter()
    unique_rows: list[dict[str, str]] = []
    for identity_rows in identities.values():
        if len(identity_rows) > 1:
            counts["skipped"] += len(identity_rows)
            logger.warning(
                "Skipping %d duplicate brand/name/merchant listings: %s / %s / %s",
                len(identity_rows),
                identity_rows[0]["brand"],
                identity_rows[0]["name"],
                identity_rows[0]["merchant"],
            )
        else:
            unique_rows.append(identity_rows[0])

    merchant_rows: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in unique_rows:
        merchant = row["merchant"].strip()
        source = MERCHANT_ALIASES.get(merchant.casefold())
        if source is None:
            counts["skipped"] += 1
            logger.warning(
                "Skipping unsupported merchant %r (listing %s)",
                merchant,
                row["product_merchant_id"],
            )
        else:
            merchant_rows[source].append(row)

    results: list[tuple[str, dict[str, str] | None]] = []
    for source, rows in merchant_rows.items():
        results.extend(
            await _refresh_merchant_rows(
                source,
                rows,
                max_workers,
                max(0.0, delay_between_requests),
            )
        )

    successful_rows: list[dict[str, str]] = []
    for status, report_row in results:
        counts[status] += 1
        if report_row is not None:
            successful_rows.append(report_row)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=REFRESH_FIELDS)
        writer.writeheader()
        writer.writerows(successful_rows)

    logger.info(
        "Price refresh complete: processed=%d skipped=%d failed=%d; output=%s",
        counts["processed"], counts["skipped"], counts["failed"], output_csv,
    )
    return counts
