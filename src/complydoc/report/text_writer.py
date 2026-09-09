"""Write the extracted text out as plain files.

Reading a scanned folder is the slow part of an audit, and complydoc has already
paid for it by the time the report is written. Throwing that away means the next
tool to want the text runs OCR over the same pages again, so `--save-text` keeps
it: one file per document, in a folder the caller names.

These files are the documents. They carry every identifier the report takes care
to mask, in full, because that is what the text of the page says. The caller is
told where they went.
"""

from __future__ import annotations

from pathlib import Path

from complydoc.report.models import AuditReport, DocumentReport

__all__ = ["write_text"]

_HEADER = "# {path}\n# sha256 {digest}\n# {pages} read by complydoc {version}\n"


def _body(document: DocumentReport) -> str:
    parts: list[str] = []
    for page in document.extracted_text:
        text = page.text or page.ocr_text
        if not text.strip():
            continue
        marker = f"--- page {page.number} ({page.source}"
        if page.truncated:
            marker += ", truncated"
        parts.append(f"{marker}) ---\n{text.rstrip()}\n")
    return "\n".join(parts)


def _destination(root: Path, relative: str) -> Path:
    """Mirror the source layout, so two invoices called the same thing stay apart."""
    target = root / (relative + ".txt")
    # A relative path can only ever point downwards, but the report's paths come
    # from a folder the caller chose, so this is checked rather than assumed.
    resolved = target.resolve()
    if not resolved.is_relative_to(root.resolve()):
        return root / (relative.replace("/", "_") + ".txt")
    return target


def write_text(report: AuditReport, directory: Path) -> list[Path]:
    """One file per document that had any text. Returns what was written."""
    directory = directory.expanduser()
    written: list[Path] = []

    for document in report.documents:
        body = _body(document)
        if not body:
            continue
        target = _destination(directory, document.relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        sources = sorted({p.source for p in document.extracted_text if p.text or p.ocr_text})
        header = _HEADER.format(
            path=document.path,
            digest=document.sha256,
            pages=f"{document.page_count} page(s), " + ", ".join(sources or ["no text"]),
            version=report.run.tool_version,
        )
        target.write_text(header + "\n" + body, encoding="utf-8")
        written.append(target)

    return written
