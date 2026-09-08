"""Table structure: how many, how deep the headers, how many merged cells.

Three signals share one file because they share one expensive extraction. Each
is still registered and reported independently.
"""

from __future__ import annotations

from complydoc.difficulty.base import ALL_FORMATS, Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document, TableInfo


def _tables(document: Document) -> list[TableInfo]:
    return [table for page in document.pages for table in page.tables]


@signal
class TableCountSignal:
    id = "table_count"
    name = "Tables detected"
    unit = "tables"
    why = (
        "Each table is a separate structure to teach a pipeline about. A handful is "
        "routine; a document full of them means the layout, not the words, is where the "
        "meaning lives."
    )
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        tables = _tables(document)
        return Measurement(
            value=len(tables),
            display=f"{len(tables)} table(s)",
            detail={
                "per_page": [len(p.tables) for p in document.pages],
                "total_rows": sum(t.rows for t in tables),
            },
        )


@signal
class TableHeaderDepthSignal:
    id = "table_max_header_depth"
    name = "Deepest table header"
    unit = "rows"
    why = (
        "A header stacked two or three rows deep means a column's real meaning is spread "
        "across several cells, so a value cannot be labelled by reading one cell above it."
    )
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        tables = _tables(document)
        if not tables:
            return Measurement.na("no tables were detected, so there is no header to measure")
        depth = max(t.header_depth for t in tables)
        return Measurement(
            value=depth,
            display=f"{depth} header row(s)",
            detail={"per_table": [t.header_depth for t in tables]},
        )


@signal
class TableMergedCellsSignal:
    id = "table_merged_cells"
    name = "Merged table cells"
    unit = "cells"
    why = (
        "A merged cell breaks the grid assumption almost every table parser makes, so "
        "values downstream of it get attributed to the wrong row or column."
    )
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        tables = _tables(document)
        if not tables:
            return Measurement.na("no tables were detected, so there are no cells to merge")
        merged = sum(t.merged_cells for t in tables)
        return Measurement(
            value=merged,
            display=f"{merged} merged cell(s)",
            detail={
                "per_table": [t.merged_cells for t in tables],
                "tables_with_merges": sum(1 for t in tables if t.merged_cells),
            },
        )
