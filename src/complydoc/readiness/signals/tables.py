"""Table structure: how many, how deep the headers, how many merged cells.

Three signals share one file because they share one expensive extraction. Each
is still registered and reported independently.
"""

from __future__ import annotations

from complydoc.ingest.base import Document, TableInfo
from complydoc.readiness.base import ALL_FORMATS, Measurement
from complydoc.readiness.registry import signal


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
                "ruled_tables": sum(1 for t in tables if t.detected_by == "lines"),
                "aligned_tables": sum(1 for t in tables if t.detected_by == "alignment"),
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
        ruled = [t for t in tables if t.detected_by == "lines"]
        if not tables:
            return Measurement.na("no tables were detected, so there is no header to measure")
        if not ruled:
            return Measurement.na(
                "the tables here are held together by whitespace rather than ruling "
                "lines, and a table with no rules carries nothing to read a span from"
            )
        depth = max(t.header_depth for t in ruled)
        return Measurement(
            value=depth,
            display=f"{depth} header rows",
            detail={"per_table": [t.header_depth for t in ruled]},
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
        ruled = [t for t in tables if t.detected_by == "lines"]
        if not tables:
            return Measurement.na("no tables were detected, so there are no cells to merge")
        if not ruled:
            return Measurement.na(
                "the tables here are held together by whitespace rather than ruling "
                "lines, so there are no spans to count"
            )
        merged = sum(t.merged_cells for t in ruled)
        return Measurement(
            value=merged,
            display=f"{merged} merged cells",
            detail={
                "per_table": [t.merged_cells for t in ruled],
                "tables_with_merges": sum(1 for t in ruled if t.merged_cells),
            },
        )
