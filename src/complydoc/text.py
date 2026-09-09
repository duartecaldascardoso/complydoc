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


def duration(seconds: float | None) -> str:
    """A human reading of a span, from milliseconds to days.

    Reports quote wall clock at wildly different scales — a page takes a fraction
    of a second, a backlog of scans takes days — so a single unit would be
    unreadable at one end or the other.
    """
    if seconds is None:
        return "—"
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 90:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f}m"
    hours = minutes / 60
    if hours < 48:
        return f"{hours:.1f}h"
    return f"{hours / 24:.1f} days"
