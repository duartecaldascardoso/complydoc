"""Self-contained HTML output.

Everything — stylesheet included — is inlined, so the file can be opened from a
USB stick or forwarded by email and still render exactly as generated. There are
no external assets and no scripts to fetch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import escape

from complydoc.config.schema import Config
from complydoc.difficulty.registry import signal_by_id
from complydoc.report.charts import SERIES, build_comparison, grouped_bars_svg
from complydoc.report.models import AuditReport
from complydoc.report.preview import PagePreview
from complydoc.text import count

__all__ = ["page_preview_svg", "render_html", "write_html"]

# The mark, inlined so the report stays a single file: a document inside the
# network guard boundary, with one line redacted.
_LOGO_SVG = (
    '<svg class="logo" viewBox="0 0 296 64" width="222" height="48" role="img" '
    'aria-label="complydoc">'
    '<rect x="8" y="12" width="40" height="40" rx="8" fill="none" stroke="var(--accent)" '
    'stroke-width="1.5" stroke-dasharray="3,3"/>'
    '<rect x="20" y="21" width="16" height="22" rx="2" fill="none" stroke="var(--ink)" '
    'stroke-width="1.5"/>'
    '<line x1="23" y1="27" x2="33" y2="27" stroke="var(--ink)" stroke-width="1.5"/>'
    '<line x1="23" y1="32" x2="33" y2="32" stroke="var(--ink)" stroke-width="1.5"/>'
    '<line x1="23" y1="37" x2="29" y2="37" stroke="var(--accent)" stroke-width="1.5"/>'
    '<text x="62" y="41" fill="var(--ink)" font-size="27" font-weight="600" '
    "font-family=\"-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif\" "
    'letter-spacing="-0.02em">complydoc</text>'
    "</svg>"
)

# The mark alone, inline so the report stays a single file.
_FAVICON_URI = (
    "data:image/svg+xml,%3Csvg%20xmlns%3D%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22%20viewBox"
    "%3D%220%200%2048%2048%22%3E%3Crect%20width%3D%2248%22%20height%3D%2248%22%20rx%3D%229%22"
    "%20fill%3D%22%23fbfbfa%22%2F%3E%3Crect%20x%3D%225%22%20y%3D%225%22%20width%3D%2238%22%20"
    "height%3D%2238%22%20rx%3D%227%22%20fill%3D%22none%22%20stroke%3D%22%231a7f4b%22%20stroke"
    "-width%3D%222.5%22%20stroke-dasharray%3D%224%2C3%22%2F%3E%3Crect%20x%3D%2216%22%20y%3D%2"
    "213%22%20width%3D%2216%22%20height%3D%2222%22%20rx%3D%222%22%20fill%3D%22none%22%20strok"
    "e%3D%22%2322272e%22%20stroke-width%3D%222.5%22%2F%3E%3Cline%20x1%3D%2219%22%20y1%3D%2219"
    "%22%20x2%3D%2229%22%20y2%3D%2219%22%20stroke%3D%22%2322272e%22%20stroke-width%3D%222.5%2"
    "2%2F%3E%3Cline%20x1%3D%2219%22%20y1%3D%2224%22%20x2%3D%2229%22%20y2%3D%2224%22%20stroke%"
    "3D%22%2322272e%22%20stroke-width%3D%222.5%22%2F%3E%3Cline%20x1%3D%2219%22%20y1%3D%2229%2"
    "2%20x2%3D%2225%22%20y2%3D%2229%22%20stroke%3D%22%231a7f4b%22%20stroke-width%3D%222.5%22%"
    "2F%3E%3C%2Fsvg%3E"
)

_PREVIEW_WIDTH = 240
_MAX_PREVIEW_PAGES = 12

_TEMPLATE_DIR = Path(__file__).parent / "templates"


def _money(value: float | None, currency: str = "USD") -> str:
    if value is None:
        return "—"
    symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency.upper(), f"{currency} ")
    if value and abs(value) < 0.01:
        return f"{symbol}{value:.5f}"
    return f"{symbol}{value:,.2f}"


def _drivers(difficulty: object, rating: str, limit: int) -> list[object]:
    """The signals that actually moved the verdict, heaviest first.

    A document has eighteen signals but only a few explain its score. Ranking by
    the weight behind each one answers "which parts make it easy or hard" without
    making the reader diff two tables of eighteen rows.
    """
    signals = getattr(difficulty, "signals", None) or []
    matching = [s for s in signals if getattr(s, "rating", None) == rating]
    matching.sort(key=lambda s: (s.weight, s.id), reverse=True)
    return matching[:limit]


def page_preview_svg(preview: PagePreview, width: int = _PREVIEW_WIDTH) -> str:
    """One page drawn as geometry: words, images, sensitive marks. No content.

    Deliberately monochrome and unlabelled — it is a thumbnail, and the numbers
    that go with it are in the table underneath.
    """
    height = max(24, round(width * preview.aspect))
    parts: list[str] = [
        f'<svg class="pv" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="Page {preview.number} layout: '
        f"{preview.text_coverage_pct}% text, {preview.image_coverage_pct}% image, "
        f'{count(preview.sensitive_count, "sensitive item")}">'
    ]

    def rect(box: object, **attrs: object) -> str:
        b = box
        x, y = b.x * width, b.y * height  # type: ignore[attr-defined]
        w, h = max(0.6, b.w * width), max(0.6, b.h * height)  # type: ignore[attr-defined]
        extra = " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in attrs.items())
        return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" {extra}/>'

    parts.append(
        f'<rect x="0" y="0" width="{width}" height="{height}" '
        f'fill="var(--pv-page)" stroke="var(--pv-edge)"/>'
    )
    for box in preview.gutters:
        parts.append(rect(box, fill="var(--pv-gutter)"))
    for box in preview.image_blocks:
        parts.append(rect(box, fill="var(--pv-image)"))
    for box in preview.text_blocks:
        parts.append(rect(box, fill="var(--pv-text)"))
    for box in preview.sensitive:
        stroke = "var(--poor)" if box.label == "high" else "var(--fair)"
        parts.append(rect(box, fill="none", stroke=stroke, stroke_width="1.2"))

    if preview.unreadable:
        parts.append(
            f'<line x1="0" y1="0" x2="{width}" y2="{height}" stroke="var(--pv-edge)"/>'
            f'<line x1="{width}" y1="0" x2="0" y2="{height}" stroke="var(--pv-edge)"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


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
            return {"label": category_id, "severity": "medium", "region": "?", "note": ""}
        return {
            "label": entry.label,
            "severity": entry.severity,
            "region": entry.region,
            "note": (entry.gdpr_note or "").strip(),
        }

    def signal_name(signal_id: str) -> str:
        found = signal_by_id(signal_id)
        return found.name if found else signal_id

    def signal_why(signal_id: str) -> str:
        """The configured wording wins, so difficulty.yaml can override a signal."""
        settings = config.difficulty.signals.get(signal_id)
        if settings is not None and settings.why:
            return settings.why
        found = signal_by_id(signal_id)
        return found.why if found else ""

    def severity_class(severity: str) -> str:
        return {"high": "r-poor", "medium": "r-fair", "low": "r-na"}.get(severity, "r-na")

    def severity_badge(severity: str) -> str:
        return f'<span class="r {severity_class(severity)}">{escape(severity)}</span>'

    def score_band(value: float) -> str:
        """Match the score bands the difficulty module labels with."""
        if value >= 75:
            return "good"
        if value >= 50:
            return "fair"
        return "poor"

    def score_class(value: float) -> str:
        if value >= 75:
            return "r-good"
        if value >= 50:
            return "r-fair"
        return "r-poor"

    comparisons = build_comparison(report)
    run = report.run
    options = [f"complydoc {' '.join(run.components_run)}"]
    if run.ocr_requested:
        options.append("--ocr" if run.ocr_available else "--ocr (unavailable)")
    else:
        options.append("--no-ocr")
    for flag, used in (
        ("--ocr-compare", run.ocr_compare_used),
        ("--page-images", run.page_images_used),
        ("--extracted-text", run.extracted_text_used),
        ("--reveal", run.reveal_used),
    ):
        if used:
            options.append(flag)
    if run.monthly_volume:
        options.append(f"--monthly-volume {run.monthly_volume:,}")
    template = environment.get_template("report.html.j2")
    return template.render(
        comparisons=comparisons,
        run_options=" ".join(options),
        series=SERIES,
        folder_chart=grouped_bars_svg(
            comparisons, "folder_usd", "Cost for this folder, by model and architecture"
        ),
        per_1000_chart=grouped_bars_svg(
            comparisons, "per_1000_usd", "Cost per 1,000 documents, by model and architecture"
        ),
        annual_chart=(
            grouped_bars_svg(comparisons, "annual_usd", "Annual cost, by model and architecture")
            if report.run.monthly_volume
            else ""
        ),
        report=report,
        page_preview_svg=page_preview_svg,
        logo_svg=_LOGO_SVG,
        favicon_uri=_FAVICON_URI,
        max_preview_pages=_MAX_PREVIEW_PAGES,
        money=lambda v: _money(v, currency),
        category_meta=category_meta,
        signal_name=signal_name,
        signal_why=signal_why,
        severity_class=severity_class,
        severity_badge=severity_badge,
        hard_drivers=lambda d, n=3: _drivers(d, "poor", n),
        easy_drivers=lambda d, n=3: _drivers(d, "good", n),
        score_band=score_band,
        score_class=score_class,
    )


def write_html(report: AuditReport, config: Config, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(report, config), encoding="utf-8")
    return path
