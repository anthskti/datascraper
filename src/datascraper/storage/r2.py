"""Cloudflare R2 image storage using its S3-compatible API."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    public_base_url: str

    @classmethod
    def from_env(cls) -> R2Config:
        required = {
            name: (os.getenv(name) or "").strip()
            for name in (
                "R2_ACCOUNT_ID",
                "R2_ACCESS_KEY_ID",
                "R2_SECRET_ACCESS_KEY",
                "R2_BUCKET",
                "R2_PUBLIC_BASE_URL",
            )
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"Missing R2 configuration: {', '.join(missing)}")

        public_base_url = required["R2_PUBLIC_BASE_URL"].rstrip("/")
        parsed_url = urlsplit(public_base_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("R2_PUBLIC_BASE_URL must be an https URL")

        return cls(
            account_id=required["R2_ACCOUNT_ID"],
            access_key_id=required["R2_ACCESS_KEY_ID"],
            secret_access_key=required["R2_SECRET_ACCESS_KEY"],
            bucket=required["R2_BUCKET"],
            public_base_url=public_base_url,
        )


class R2Storage:
    def __init__(self, config: R2Config) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("R2 uploads require boto3; install project dependencies") from exc

        self.config = config
        self.client = boto3.client(
            "s3",
            endpoint_url=f"https://{config.account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name="auto",
        )

    def public_url(self, key: str) -> str:
        return f"{self.config.public_base_url}/{key}"

    def upload_webp(self, key: str, content: bytes) -> str:
        self.client.put_object(
            Bucket=self.config.bucket,
            Key=key,
            Body=content,
            ContentType="image/webp",
            CacheControl="public, max-age=31536000, immutable",
        )
        return self.public_url(key)
