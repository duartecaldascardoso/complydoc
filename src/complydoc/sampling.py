"""Pick a representative subset of a large folder.

A folder of fifty thousand invoices takes a long time to audit in full, and the
answer barely moves after the first few hundred. `--sample` cuts the run down,
but a sample is only useful if it is honest about two things: which documents it
chose, and that the numbers are a sample rather than a total.

The choice is deterministic — no random seed to record, no two runs of the same
folder disagreeing. Files are grouped by extension and each group keeps its
share of the sample, so a folder that is 90% PDF and 10% spreadsheet produces a
sample that is 90% PDF and 10% spreadsheet rather than whatever the alphabet
happened to put first.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

__all__ = ["sample_files"]


def _evenly_spaced(items: list[Path], take: int) -> list[Path]:
    """`take` items spread across the list, always including the first."""
    if take <= 0:
        return []
    if take >= len(items):
        return list(items)
    step = len(items) / take
    return [items[int(i * step)] for i in range(take)]


def _allocate(sizes: dict[str, int], total: int, limit: int) -> dict[str, int]:
    """Split `limit` between groups in proportion to their size.

    Whole shares first, then the remaining places go to the groups with the
    largest fractional claim. When there are at least as many places as groups,
    every group is guaranteed one, so a folder of ten thousand PDFs and three
    spreadsheets still puts a spreadsheet in front of the reader.
    """
    exact = {key: size * limit / total for key, size in sizes.items()}
    allocation = {key: min(sizes[key], int(value)) for key, value in exact.items()}

    while sum(allocation.values()) < limit:
        candidates = [k for k in allocation if allocation[k] < sizes[k]]
        if not candidates:
            break
        allocation[max(candidates, key=lambda k: exact[k] - allocation[k])] += 1

    if limit >= len(sizes):
        for key in sorted(allocation, key=lambda k: exact[k]):
            if allocation[key]:
                continue
            donor = max(allocation, key=lambda k: allocation[k])
            if allocation[donor] < 2:
                break
            allocation[donor] -= 1
            allocation[key] = 1

    return allocation


def sample_files(files: list[Path], limit: int) -> list[Path]:
    """Up to `limit` files, keeping each file type's share of the folder."""
    if limit <= 0 or limit >= len(files):
        return list(files)

    groups: dict[str, list[Path]] = defaultdict(list)
    for path in files:
        groups[path.suffix.lower()].append(path)

    sizes = {key: len(value) for key, value in groups.items()}
    allocation = _allocate(sizes, len(files), limit)

    chosen: set[Path] = set()
    for key, take in allocation.items():
        chosen.update(_evenly_spaced(groups[key], take))
    return [path for path in files if path in chosen]
