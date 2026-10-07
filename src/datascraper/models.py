"""Shared product output schema."""

from typing import TypedDict


OUTPUT_FIELDS = [
    "name",
    "brand",
    "category",
    "labels",
    "skinType",
    "country",
    "capacity",
    "price",
    "instructions",
    "ingredients",
    "imageUrls",
    "averageRating",
    "url",
    "merchant",
    "status",
]


class Product(TypedDict):
    name: str
    brand: str
    category: str
    labels: str
    skinType: str
    country: str
    capacity: str
    price: str
    instructions: str
    ingredients: str
    imageUrls: str
    averageRating: str
    url: str
    merchant: str
    status: str
