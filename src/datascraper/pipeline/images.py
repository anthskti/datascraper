"""Download, optimize, and ingest product images into R2."""

from __future__ import annotations

import csv
import hashlib
import ipaddress
import io
import json
import logging
import os
import socket
import tempfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps

from datascraper.models import OUTPUT_FIELDS
from datascraper.storage.r2 import R2Config, R2Storage

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PROGRESS = _ROOT / "outputs" / "progress" / "image_ingest_progress.jsonl"
_MAX_IMAGE_BYTES = 20 * 1024 * 1024
_MAX_IMAGE_WIDTH = 800


def _image_urls(value: str | None) -> list[str]:
    if not value or value.strip() in {"", "N/A"}:
        return []
    return [url.strip() for url in value.split("|") if url.strip() and url.strip() != "N/A"]


def _is_success(row: dict[str, str]) -> bool:
    return (row.get("status") or "").strip().lower() == "success"


def _product_digest(brand: str, name: str) -> str:
    brand = (brand or "").strip()
    name = (name or "").strip()
    if not brand or not name:
        raise ValueError("Cannot create image key without brand and product name")
    identity = f"{brand.strip().lower()}::{name.strip().lower()}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _image_key(brand: str, name: str, index: int, source_url: str) -> str:
    product_id = _product_digest(brand, name)
    source_id = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:12]
    return f"products/{product_id}/{index}-{source_id}.webp"


def _validate_public_image_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Image URL must be a valid http or https URL") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Image URL must use http or https and must not contain credentials")

    expected_port = 443 if parsed.scheme == "https" else 80
    if port is not None and port != expected_port:
        raise ValueError("Image URL must use the standard http or https port")
    port = expected_port

    try:
        addresses = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("Image host could not be resolved") from exc
    try:
        has_non_public_address = any(
            not ipaddress.ip_address(address[4][0]).is_global for address in addresses
        )
    except ValueError as exc:
        raise ValueError("Image host resolved to an invalid IP address") from exc
    if not addresses or has_non_public_address:
        raise ValueError("Image host must resolve only to public IP addresses")


class _PublicRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_image_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download_image(url: str) -> bytes:
    _validate_public_image_url(url)

    request = Request(url, headers={"User-Agent": "datascraper/0.1"})
    try:
        with build_opener(_PublicRedirectHandler()).open(request, timeout=30) as response:
            _validate_public_image_url(response.geturl())
            content = response.read(_MAX_IMAGE_BYTES + 1)
    except URLError as exc:
        raise ValueError(f"Image download failed: {exc}") from exc
    if len(content) > _MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds the 20 MB download limit")
    return content


def _to_webp(content: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            if image.width > _MAX_IMAGE_WIDTH:
                height = max(1, round(image.height * _MAX_IMAGE_WIDTH / image.width))
                image = image.resize(
                    (_MAX_IMAGE_WIDTH, height),
                    Image.Resampling.LANCZOS,
                )
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=85, method=6)
            return output.getvalue()
    except Exception as exc:
        raise ValueError(f"Image could not be decoded or converted to WebP: {exc}") from exc


def _load_progress(path: Path, account_id: str, bucket: str) -> set[str]:
    completed: set[str] = set()
    if not path.exists():
        return completed
    with path.open(encoding="utf-8") as progress_file:
        for line in progress_file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                isinstance(record, dict)
                and record.get("account_id") == account_id
                and record.get("bucket") == bucket
                and isinstance(record.get("key"), str)
            ):
                completed.add(record["key"])
    return completed


def _record_progress(path: Path, account_id: str, bucket: str, key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as progress_file:
        progress_file.write(
            json.dumps({"account_id": account_id, "bucket": bucket, "key": key}) + "\n"
        )
        progress_file.flush()
        os.fsync(progress_file.fileno())


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as output_file:
        temp_path = Path(output_file.name)
        writer = csv.DictWriter(output_file, fieldnames=OUTPUT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp_path, path)


def ingest_images(
    input_csv: Path,
    output_csv: Path,
    *,
    dry_run: bool = False,
    progress_path: Path | None = None,
) -> int:
    """Write an import CSV with R2 image URLs, preserving input on failure."""
    if input_csv.resolve() == output_csv.resolve():
        raise ValueError("Input and output CSV paths must be different")
    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv}")

    with input_csv.open(newline="", encoding="utf-8-sig") as input_file:
        reader = csv.DictReader(input_file)
        required_fields = {"name", "brand", "imageUrls", "status", "skinTypeSource"}
        if not reader.fieldnames or not required_fields.issubset(reader.fieldnames):
            raise ValueError(
                "Input CSV must contain name, brand, imageUrls, status, and skinTypeSource columns"
            )
        rows = [dict(row) for row in reader]

    urls_by_row: list[list[str]] = [_image_urls(row.get("imageUrls")) for row in rows]
    eligible_rows = [
        index
        for index, (row, urls) in enumerate(zip(rows, urls_by_row))
        if _is_success(row) and urls
    ]
    total_images = sum(len(urls_by_row[index]) for index in eligible_rows)
    skipped_rows = len(rows) - len(eligible_rows)
    if dry_run:
        failures: list[str] = []
        for row_index in eligible_rows:
            row = rows[row_index]
            urls = urls_by_row[row_index]
            for index, source_url in enumerate(urls, start=1):
                try:
                    key = _image_key(
                        row.get("brand") or "", row.get("name") or "", index, source_url
                    )
                    logger.info("Would ingest %s as %s", source_url, key)
                except ValueError as exc:
                    failures.append(f"{row.get('brand', '')} / {row.get('name', '')}: {exc}")
        logger.info(
            "Dry run: planned %d image uploads from %d rows; skipped %d unsuccessful or imageless rows; no downloads or uploads performed",
            total_images,
            len(eligible_rows),
            skipped_rows,
        )
        if failures:
            for failure in failures:
                logger.error("%s", failure)
            raise RuntimeError(f"Dry run found {len(failures)} row(s) that cannot be ingested")
        return total_images

    state_path = progress_path or _DEFAULT_PROGRESS
    if state_path.resolve() in {input_csv.resolve(), output_csv.resolve()}:
        raise ValueError("Progress file must be different from input and output CSV paths")
    config = R2Config.from_env()
    storage = R2Storage(config)
    completed = _load_progress(state_path, config.account_id, config.bucket)
    replacements: list[list[str]] = [[] for _ in rows]
    processed_rows = 0
    failed_rows = 0
    failures: list[str] = []

    for row_index in eligible_rows:
        row = rows[row_index]
        urls = urls_by_row[row_index]
        failed_url = "N/A"
        try:
            _product_digest(row.get("brand") or "", row.get("name") or "")
            for index, source_url in enumerate(urls, start=1):
                failed_url = source_url
                key = _image_key(
                    row.get("brand") or "", row.get("name") or "", index, source_url
                )
                if key in completed:
                    replacements[row_index].append(storage.public_url(key))
                    continue
                webp = _to_webp(_download_image(source_url))
                public_url = storage.upload_webp(key, webp)
                _record_progress(state_path, config.account_id, config.bucket, key)
                completed.add(key)
                replacements[row_index].append(public_url)
                logger.info("Uploaded %s", key)
            processed_rows += 1
        except Exception as exc:
            failed_rows += 1
            failures.append(
                f"Row {row_index + 2} ({row.get('brand', '')} / {row.get('name', '')}), "
                f"{failed_url}: {exc}"
            )

    logger.info(
        "Image ingest summary: processed: %d, skipped: %d, failed: %d",
        processed_rows,
        skipped_rows,
        failed_rows,
    )
    if failures:
        logger.error("Image ingest incomplete; no output CSV written")
        for failure in failures:
            logger.error("%s", failure)
        raise RuntimeError(f"Image ingest failed for {failed_rows} row(s); rerun to resume")

    output_rows: list[dict[str, str]] = []
    for row_index in eligible_rows:
        row = dict(rows[row_index])
        row["imageUrls"] = "|".join(replacements[row_index])
        output_rows.append(row)
    _write_csv(output_csv, output_rows)
    logger.info(
        "Wrote image import CSV to %s (%d rows, %d images)",
        output_csv,
        len(output_rows),
        total_images,
    )
    return total_images
