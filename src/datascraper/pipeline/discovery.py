"""Conservative comparison of scraped products with the existing catalog CSV."""

import csv
import logging
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from datascraper.models import OUTPUT_FIELDS
from datascraper.taxonomy import normalize_product_capacity, normalize_product_identity_text

logger = logging.getLogger(__name__)

REPORT_FIELDS = [
    "reviewReason",
    "matchedName",
    "matchedBrand",
    "matchedCapacity",
    "matchedUrl",
]
_FUZZY_NAME_THRESHOLD = 0.88


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header row: {path}")
        return [
            {str(key).strip(): (value or "").strip() for key, value in row.items() if key}
            for row in reader
        ]


def _field(row: dict[str, str], name: str) -> str:
    for key, value in row.items():
        if key.casefold() == name.casefold():
            return value
    return ""


def _normalized_url(value: str) -> str:
    if not value.strip() or value.strip().casefold() in {"n/a", "na", "none"}:
        return ""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return value.strip().casefold()
    if not parts.scheme or not parts.netloc:
        return value.strip().casefold()
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), "", ""))


def _identity(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        normalize_product_identity_text(_field(row, "brand")),
        normalize_product_identity_text(_field(row, "name")),
        normalize_product_capacity(_field(row, "capacity")),
    )


def _report_row(
    row: dict[str, str],
    *,
    reason: str,
    matched: dict[str, str] | None = None,
) -> dict[str, str]:
    output = {field: _field(row, field) for field in OUTPUT_FIELDS}
    output.update(
        {
            "reviewReason": reason,
            "matchedName": _field(matched or {}, "name"),
            "matchedBrand": _field(matched or {}, "brand"),
            "matchedCapacity": _field(matched or {}, "capacity"),
            "matchedUrl": _field(matched or {}, "url"),
        }
    )
    return output


def _write_rows(path: Path, rows: list[dict[str, str]], *, report: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = OUTPUT_FIELDS + REPORT_FIELDS if report else OUTPUT_FIELDS
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compare_with_catalog(
    input_csv: Path,
    catalog_csv: Path,
    output_prefix: Path,
) -> dict[str, int]:
    """Split successful scraped rows into new, existing, and manual-review CSVs."""
    scraped_rows = _read_csv(input_csv)
    catalog_rows = [
        row
        for row in _read_csv(catalog_csv)
        if _field(row, "status").casefold() not in {"failed", "blocked"}
    ]

    by_brand_name: dict[tuple[str, str], list[dict[str, str]]] = {}
    by_brand: dict[str, list[dict[str, str]]] = {}
    by_name: dict[str, list[dict[str, str]]] = {}
    catalog_urls: dict[str, dict[str, str]] = {}
    for row in catalog_rows:
        brand_key, name_key, _ = _identity(row)
        if brand_key and name_key:
            by_brand_name.setdefault((brand_key, name_key), []).append(row)
            by_brand.setdefault(brand_key, []).append(row)
            by_name.setdefault(name_key, []).append(row)
        url_key = _normalized_url(_field(row, "url"))
        if url_key:
            catalog_urls.setdefault(url_key, row)

    new_rows: list[dict[str, str]] = []
    existing_rows: list[dict[str, str]] = []
    review_rows: list[dict[str, str]] = []

    for row in scraped_rows:
        if _field(row, "status").casefold() != "success":
            review_rows.append(_report_row(row, reason="scrape_not_successful"))
            continue

        brand_key, name_key, capacity_key = _identity(row)
        if not brand_key or not name_key:
            review_rows.append(_report_row(row, reason="missing_brand_or_name"))
            continue

        url_key = _normalized_url(_field(row, "url"))
        if url_key and url_key in catalog_urls:
            existing_rows.append(
                _report_row(row, reason="same_listing_url", matched=catalog_urls[url_key])
            )
            continue

        same_name = by_brand_name.get((brand_key, name_key), [])
        if same_name:
            capacity_matches = [
                candidate
                for candidate in same_name
                if capacity_key and _identity(candidate)[2] == capacity_key
            ]
            if capacity_matches:
                existing_rows.append(
                    _report_row(
                        row,
                        reason="same_brand_name_and_capacity",
                        matched=capacity_matches[0],
                    )
                )
            else:
                review_rows.append(
                    _report_row(
                        row,
                        reason="capacity_missing_or_different",
                        matched=same_name[0],
                    )
                )
            continue

        if name_key in by_name:
            review_rows.append(
                _report_row(row, reason="same_name_different_brand", matched=by_name[name_key][0])
            )
            continue

        close_matches = [
            (SequenceMatcher(None, name_key, _identity(candidate)[1]).ratio(), candidate)
            for candidate in by_brand.get(brand_key, [])
            if _identity(candidate)[1]
        ]
        close_matches = [item for item in close_matches if item[0] >= _FUZZY_NAME_THRESHOLD]
        if close_matches:
            best_match = max(close_matches, key=lambda item: item[0])[1]
            review_rows.append(_report_row(row, reason="similar_name_same_brand", matched=best_match))
            continue

        new_rows.append({field: _field(row, field) for field in OUTPUT_FIELDS})

    prefix = output_prefix
    counts = {
        "new": len(new_rows),
        "existing": len(existing_rows),
        "review": len(review_rows),
    }
    _write_rows(prefix.with_name(f"{prefix.name}_new.csv"), new_rows)
    _write_rows(prefix.with_name(f"{prefix.name}_existing.csv"), existing_rows, report=True)
    _write_rows(prefix.with_name(f"{prefix.name}_review.csv"), review_rows, report=True)
    logger.info(
        "Catalog comparison complete: new=%d existing=%d review=%d",
        counts["new"],
        counts["existing"],
        counts["review"],
    )
    return counts
