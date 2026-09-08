"""JSON output, for machine consumption and for diffing runs over time."""

from __future__ import annotations

import json
from pathlib import Path

from complydoc.report.models import AuditReport, to_jsonable

__all__ = ["to_dict", "write_json"]


def to_dict(report: AuditReport) -> dict[str, object]:
    return dict(to_jsonable(report))


def write_json(report: AuditReport, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys keeps two runs comparable with a plain diff.
    path.write_text(
        json.dumps(to_dict(report), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
