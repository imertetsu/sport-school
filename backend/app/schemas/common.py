"""Schemas comunes: paginación (C5)."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Envoltura de paginación: `{items, total, page, page_size}` (C5)."""

    items: list[T]
    total: int
    page: int
    page_size: int
