"""Word document loader.

A DOCX has no fixed pagination until it is laid out, so the whole body is
presented as a single logical page and `page_count_known` is set to False. The
report says so rather than quoting a page count that came from nowhere.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import docx
from docx.opc.exceptions import PackageNotFoundError

from complydoc.ingest.base import (
    Document,
    DocumentFormat,
    IngestOptions,
    LoaderError,
    Page,
    TableInfo,
    sha256_of,
)
from complydoc.ingest.registry import register

_EMU_PER_POINT = 12700


def _table_info(table: Any) -> TableInfo:
    rows = len(table.rows)
    cols = len(table.columns) if table.columns else 0

    unique_cells: set[int] = set()
    header_depth = 0
    counting_header = True
    for row in table.rows:
        try:
            cells = list(row.cells)
        except Exception:
            continue
        ids = {id(cell._tc) for cell in cells}
        unique_cells |= ids
        row_is_merged = len(ids) < len(cells)
        if counting_header and row_is_merged:
            header_depth += 1
        elif counting_header:
            counting_header = False

    merged = max(0, rows * cols - len(unique_cells))
    # The row of leaf labels under the spanning rows counts as header as well.
    depth = header_depth + 1 if header_depth else 1
    return TableInfo(rows=rows, cols=cols, header_depth=depth, merged_cells=merged)


class DocxLoader:
    extensions: tuple[str, ...] = (".docx",)
    format: DocumentFormat = DocumentFormat.DOCX

    def load(self, path: Path, options: IngestOptions) -> Document:
        document = Document(
            path=path,
            sha256=sha256_of(path),
            format=self.format,
            page_count_known=False,
        )

        try:
            source = docx.Document(str(path))
        except (PackageNotFoundError, ValueError, KeyError) as exc:
            raise LoaderError(f"python-docx could not open the file: {exc}") from exc

        width_pt = height_pt = 0.0
        try:
            section = source.sections[0]
            if section.page_width and section.page_height:
                width_pt = float(section.page_width) / _EMU_PER_POINT
                height_pt = float(section.page_height) / _EMU_PER_POINT
        except (IndexError, AttributeError):
            pass

        page = Page(number=1, width_pt=width_pt, height_pt=height_pt)

        parts: list[str] = [p.text for p in source.paragraphs if p.text.strip()]
        fonts: set[str] = set()
        for paragraph in source.paragraphs:
            for run in paragraph.runs:
                name = getattr(run.font, "name", None)
                if name:
                    fonts.add(str(name))

        for table in source.tables:
            try:
                page.tables.append(_table_info(table))
            except Exception as exc:
                document.load_warnings.append(f"A table could not be analysed ({exc}).")
            for row in table.rows:
                try:
                    parts.extend(cell.text for cell in row.cells if cell.text.strip())
                except Exception:
                    continue

        page.text = "\n".join(parts)
        page.text_source = "native" if page.text.strip() else "none"
        page.fonts = fonts
        page.embedded_fonts = None
        page.notes.append(
            "DOCX pagination depends on the renderer, so the whole document is treated "
            "as one logical page."
        )
        document.pages.append(page)
        document.load_warnings.append(
            "Page count, page dimensions and scan resolution are not determinable for a "
            "DOCX without rendering it, so they were not measured."
        )
        return document


register(DocxLoader())
