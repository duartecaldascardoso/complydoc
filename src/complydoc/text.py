"""Small text helpers.

`plural` exists so no message has to say "3 page(s)". A report that a business
reader is meant to act on should read like it was written, not templated.
"""

from __future__ import annotations

__all__ = ["count", "plural"]


def plural(quantity: int, singular: str, many: str | None = None) -> str:
    """The right word for the quantity, without the number."""
    if quantity == 1:
        return singular
    return many if many is not None else f"{singular}s"


def count(quantity: int, singular: str, many: str | None = None) -> str:
    """The quantity and the right word for it, e.g. "1 page" or "3 pages"."""
    return f"{quantity:,} {plural(quantity, singular, many)}"
