"""Self-contained HTML output.

Everything — stylesheet included — is inlined, so the file can be opened from a
USB stick or forwarded by email and still render exactly as generated. There are
no external assets and no scripts to fetch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from complydoc.config.schema import Config
from complydoc.difficulty.registry import signal_by_id
from complydoc.report.models import AuditReport

__all__ = ["render_html", "write_html"]

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _money(value: float | None, currency: str = "USD") -> str:
    if value is None:
        return "—"
    symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency.upper(), f"{currency} ")
    if value and abs(value) < 0.01:
        return f"{symbol}{value:.5f}"
    return f"{symbol}{value:,.2f}"


def render_html(report: AuditReport, config: Config) -> str:
    environment = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    currency = report.aggregate.currency if report.aggregate else "USD"

    def category_meta(category_id: str) -> dict[str, Any]:
        entry = config.sensitive.categories.get(category_id)
        if entry is None:
            return {"label": category_id, "severity": "medium", "note": ""}
        return {
            "label": entry.label,
            "severity": entry.severity,
            "note": (entry.gdpr_note or "").strip(),
        }

    def signal_name(signal_id: str) -> str:
        found = signal_by_id(signal_id)
        return found.name if found else signal_id

    def severity_class(severity: str) -> str:
        return {"high": "r-poor", "medium": "r-fair", "low": "r-na"}.get(severity, "r-na")

    def score_class(value: float) -> str:
        if value >= 75:
            return "r-good"
        if value >= 50:
            return "r-fair"
        return "r-poor"

    template = environment.get_template("report.html.j2")
    return template.render(
        report=report,
        money=lambda v: _money(v, currency),
        category_meta=category_meta,
        signal_name=signal_name,
        severity_class=severity_class,
        score_class=score_class,
    )


def write_html(report: AuditReport, config: Config, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report, config), encoding="utf-8")
    return path
