"""Cost comparison across processing architectures, and the charts for it.

Three ways to get a document in front of a model, each with a different price and,
more importantly, a different reach:

- **Text layer** — read the text the file already carries. Cheapest, but it only
  works on documents that have one.
- **Text + local OCR** — same tokens, same price, but scans are read locally first,
  so it reaches every document. The OCR itself costs nothing to the provider.
- **Vision** — send the rendered page. Reaches everything, costs the most.

Cost alone would make the first look best. It is only best for the documents it can
actually serve, so reach is reported beside every figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from complydoc.report.models import AuditReport

__all__ = ["ArchitectureCost", "ModelComparison", "build_comparison", "grouped_bars_svg"]

# Categorical series colours, held as CSS variables so light and dark can differ.
# Deliberately not the report's green/amber/red, which carry status meaning here;
# reusing them would say "vision is bad".
#
# Both sets were validated against their own surface rather than flipped:
#   light  #2a78d6 blue / #4a3aa7 violet / #e87ba4 magenta  — CVD 13.0, normal 16.3
#   dark   #3987e5 blue / #d55181 magenta / #c98500 yellow  — CVD 13.2, normal 19.3
# Blue and magenta keep their hue across modes; the middle slot cannot, because
# violet and blue are indistinguishable to a protanope on a dark surface (ΔE 1.9).
SERIES = (
    ("text_layer", "Text layer", "var(--series-1)"),
    ("text_ocr", "Text + local OCR", "var(--series-2)"),
    ("vision", "Vision", "var(--series-3)"),
)

_NOTES = {
    "text_layer": "Only documents that already carry a text layer.",
    "text_ocr": "Every document. Scans are read locally first, which costs nothing to send.",
    "vision": "Every document, sent as page images.",
}


@dataclass(frozen=True, slots=True)
class ArchitectureCost:
    key: str
    label: str
    folder_usd: float | None
    per_document_usd: float | None
    per_1000_usd: float | None
    annual_usd: float | None
    documents_served: int
    documents_total: int
    note: str

    @property
    def reach_pct(self) -> float:
        if not self.documents_total:
            return 0.0
        return self.documents_served / self.documents_total * 100


@dataclass(slots=True)
class ModelComparison:
    model_id: str
    display_name: str
    architectures: list[ArchitectureCost] = field(default_factory=list)

    def by_key(self, key: str) -> ArchitectureCost | None:
        return next((a for a in self.architectures if a.key == key), None)


def build_comparison(report: AuditReport) -> list[ModelComparison]:
    """Folder cost per model under each architecture."""
    if report.cost is None or not report.cost.documents:
        return []

    resolution = report.cost.headline_resolution
    volume = report.run.monthly_volume
    total_documents = len(report.cost.documents)
    model_ids = [m.model_id for m in report.cost.documents[0].models]

    comparisons: list[ModelComparison] = []
    for index, model_id in enumerate(model_ids):
        display = report.cost.documents[0].models[index].display_name
        buckets: dict[str, tuple[float, int]] = {k: (0.0, 0) for k, _, _ in SERIES}

        for estimate in report.cost.documents:
            model = estimate.models[index]
            text = model.text_path_input_usd
            vision = model.vision_input_usd_by_resolution.get(resolution)

            if text is not None:
                total, served = buckets["text_ocr"]
                buckets["text_ocr"] = (total + text, served + 1)
                if estimate.has_text_layer:
                    total, served = buckets["text_layer"]
                    buckets["text_layer"] = (total + text, served + 1)
            if vision is not None:
                total, served = buckets["vision"]
                buckets["vision"] = (total + vision, served + 1)

        architectures: list[ArchitectureCost] = []
        for key, label, _ in SERIES:
            total, served = buckets[key]
            per_document = total / served if served else None
            architectures.append(
                ArchitectureCost(
                    key=key,
                    label=label,
                    folder_usd=total if served else None,
                    per_document_usd=per_document,
                    per_1000_usd=per_document * 1000 if per_document is not None else None,
                    annual_usd=(
                        per_document * volume * 12 if per_document is not None and volume else None
                    ),
                    documents_served=served,
                    documents_total=total_documents,
                    note=_NOTES[key],
                )
            )
        comparisons.append(
            ModelComparison(model_id=model_id, display_name=display, architectures=architectures)
        )
    return comparisons


def _bar_path(x: float, y: float, width: float, height: float, radius: float = 4.0) -> str:
    """A bar anchored to the baseline with only its value end rounded."""
    r = max(0.0, min(radius, width, height / 2))
    if r <= 0 or width <= 0:
        return f"M {x},{y} h {max(width, 0.6)} v {height} h {-max(width, 0.6)} Z"
    return (
        f"M {x},{y} H {x + width - r} A {r},{r} 0 0 1 {x + width},{y + r} "
        f"V {y + height - r} A {r},{r} 0 0 1 {x + width - r},{y + height} H {x} Z"
    )


def grouped_bars_svg(
    comparisons: list[ModelComparison],
    value: str,
    title: str,
    unit_prefix: str = "$",
) -> str:
    """Horizontal grouped bars: one group per model, one bar per architecture.

    Values are labelled directly on every bar, and the same numbers appear in the
    table underneath. Two of the three series sit below 3:1 against the page, so
    identity never rests on the fill alone.
    """
    rows = [
        (c, [(k, label, colour, getattr(c.by_key(k), value, None)) for k, label, colour in SERIES])
        for c in comparisons
    ]
    values = [v for _, series in rows for *_, v in series if v is not None]
    if not values:
        return ""

    peak = max(values)
    bar_h, gap, group_gap = 14, 2, 22
    label_w, right_pad, top = 132, 96, 34
    plot_w = 420
    group_h = len(SERIES) * bar_h + (len(SERIES) - 1) * gap
    height = top + len(rows) * (group_h + group_gap)
    width = label_w + plot_w + right_pad

    # One precision for the whole chart, chosen from its largest value. Mixing
    # "$0.00848" and "$0.01" in the same group reads as two different accuracies
    # when it is one.
    decimals = 2 if peak >= 1 else (4 if peak >= 0.01 else 6)

    def money(v: float) -> str:
        return f"{unit_prefix}{v:,.{decimals}f}"

    parts = [
        f'<svg class="chart" viewBox="0 0 {width} {height}" width="100%" '
        f'height="{height}" role="img" aria-label="{title}">'
    ]
    # Recessive axis only; no grid competing with the marks.
    parts.append(
        f'<line x1="{label_w}" y1="{top - 10}" x2="{label_w}" y2="{height - 12}" '
        f'stroke="var(--line)" stroke-width="1"/>'
    )

    y = top
    for comparison, series in rows:
        parts.append(
            f'<text x="{label_w - 10}" y="{y + group_h / 2 + 4}" text-anchor="end" '
            f'font-size="12" font-weight="600" fill="var(--ink)">{comparison.display_name}</text>'
        )
        for _key, label, colour, amount in series:
            if amount is None:
                parts.append(
                    f'<text x="{label_w + 6}" y="{y + bar_h - 3}" font-size="10" '
                    f'fill="var(--muted)">{label} — not applicable</text>'
                )
            else:
                bar_w = (amount / peak) * plot_w if peak else 0
                parts.append(
                    f'<path d="{_bar_path(label_w, y, bar_w, bar_h)}" fill="{colour}">'
                    f"<title>{comparison.display_name} · {label} · {money(amount)}</title></path>"
                )
                parts.append(
                    f'<text x="{label_w + bar_w + 8}" y="{y + bar_h - 3}" font-size="10.5" '
                    f'fill="var(--ink-2)">{money(amount)}</text>'
                )
            y += bar_h + gap
        y += group_gap - gap

    parts.append("</svg>")
    return "".join(parts)
