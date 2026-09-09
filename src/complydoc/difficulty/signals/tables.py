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
    why = "Every table is another structure to teach a pipeline about."
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        if not document.pages:
            return Measurement.na(
                "the document could not be opened, so it has no pages to look for tables in"
            )
        tables = _tables(document)
        return Measurement(
            value=len(tables),
            display=f"{len(tables)} tables",
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
    why = "A header stacked several rows deep spreads one column's meaning across cells."
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        tables = _tables(document)
        if not tables:
            return Measurement.na("no tables were detected, so there is no header to measure")
        depth = max(t.header_depth for t in tables)
        return Measurement(
            value=depth,
            display=f"{depth} header rows",
            detail={"per_table": [t.header_depth for t in tables]},
        )


@signal
class TableMergedCellsSignal:
    id = "table_merged_cells"
    name = "Merged table cells"
    unit = "cells"
    why = "A merged cell breaks the grid, so values land in the wrong row or column."
    applies_to = ALL_FORMATS

    def measure(self, document: Document) -> Measurement:
        tables = _tables(document)
        if not tables:
            return Measurement.na("no tables were detected, so there are no cells to merge")
        merged = sum(t.merged_cells for t in tables)
        return Measurement(
            value=merged,
            display=f"{merged} merged cells",
            detail={
                "per_table": [t.merged_cells for t in tables],
                "tables_with_merges": sum(1 for t in tables if t.merged_cells),
            },
        )
