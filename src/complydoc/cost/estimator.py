"""Component 1: what these documents would cost to put through an LLM.

Two paths are costed for every model. The text path assumes the document's own
text layer is extracted locally and only text is sent. The vision path assumes
each page is rendered and sent as an image. For a scanned document the text path
is not available at all, and saying so is more useful than quoting a cost of zero.

Only input cost is estimated. Output length depends entirely on what you ask the
model to produce, which this tool cannot know, so it is left out rather than
guessed at.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from complydoc.config.schema import ModelPricing, PricingConfig
from complydoc.cost.tokenizer import TokenCount, count_tokens
from complydoc.cost.vision import RenderedSize, rendered_size, vision_tokens
from complydoc.geometry import coverage_fraction
from complydoc.ingest.base import Document
from complydoc.text import count

__all__ = [
    "DocumentCostEstimate",
    "FolderCostEstimate",
    "ModelCostEstimate",
    "PageFacts",
    "UnknownModelError",
    "VolumeExtrapolation",
    "estimate_document",
    "estimate_folder",
    "resolve_models",
]


@dataclass(frozen=True, slots=True)
class PageFacts:
    number: int
    width_pt: float
    height_pt: float
    dpi: float | None
    text_source: str
    text_coverage_pct: float
    rendered: dict[str, RenderedSize]

    @property
    def size_label(self) -> str:
        if self.width_pt <= 0 or self.height_pt <= 0:
            return "not determinable"
        return f"{self.width_pt:.0f} x {self.height_pt:.0f} pt"


@dataclass(frozen=True, slots=True)
class ModelCostEstimate:
    model_id: str
    display_name: str
    provider: str
    input_per_mtok_usd: float
    last_verified: dt.date | None
    days_since_verified: int | None
    is_stale: bool
    text_tokens: int
    text_token_fidelity: str
    text_token_note: str | None
    text_path_input_usd: float | None
    """None when the document has no usable text layer, so the path does not exist."""
    text_path_unavailable_reason: str | None
    vision_tokens_by_resolution: dict[str, int]
    vision_input_usd_by_resolution: dict[str, float]
    vision_path_unavailable_reason: str | None
    """None when the vision path was costed. Set when it could not be."""
    text_path_seconds: float | None
    """Only set when the model carries a measured throughput in pricing.yaml."""
    vision_formula: str | None


@dataclass(frozen=True, slots=True)
class DocumentCostEstimate:
    path: Path
    page_count: int
    page_count_known: bool
    has_text_layer: bool
    mean_text_coverage_pct: float
    pages: list[PageFacts]
    models: list[ModelCostEstimate]

    def cheapest_text_path_usd(self) -> float | None:
        values = [m.text_path_input_usd for m in self.models if m.text_path_input_usd is not None]
        return min(values) if values else None

    def cheapest_vision_path_usd(self, resolution: str) -> float | None:
        values = [
            m.vision_input_usd_by_resolution[resolution]
            for m in self.models
            if resolution in m.vision_input_usd_by_resolution
        ]
        return min(values) if values else None


@dataclass(frozen=True, slots=True)
class VolumeExtrapolation:
    monthly_volume: int
    documents_measured: int
    mean_text_path_usd: float | None
    mean_vision_path_usd: float | None
    monthly_text_usd: float | None
    monthly_vision_usd: float | None
    annual_text_usd: float | None
    annual_vision_usd: float | None
    basis: str


@dataclass(slots=True)
class FolderCostEstimate:
    currency: str
    usd_to_report_rate: float | None
    headline_resolution: str
    resolutions: list[str]
    documents: list[DocumentCostEstimate] = field(default_factory=list)
    volume: VolumeExtrapolation | None = None

    def total_text_path_usd(self) -> float | None:
        values = [d.cheapest_text_path_usd() for d in self.documents]
        present = [v for v in values if v is not None]
        return sum(present) if present else None

    def total_vision_path_usd(self, resolution: str) -> float | None:
        values = [d.cheapest_vision_path_usd(resolution) for d in self.documents]
        present = [v for v in values if v is not None]
        return sum(present) if present else None


def _page_facts(document: Document, pricing: PricingConfig) -> list[PageFacts]:
    facts: list[PageFacts] = []
    for page in document.pages:
        coverage = coverage_fraction(
            [block.bbox for block in page.text_blocks], page.width_pt, page.height_pt
        )
        image_coverage = coverage_fraction(
            [block.bbox for block in page.image_blocks], page.width_pt, page.height_pt
        )
        # DPI only means something where the page really is a scan.
        dpi = page.estimated_dpi() if image_coverage > 0.5 else None
        facts.append(
            PageFacts(
                number=page.number,
                width_pt=page.width_pt,
                height_pt=page.height_pt,
                dpi=round(dpi, 1) if dpi else None,
                text_source=page.text_source,
                text_coverage_pct=round(coverage * 100.0, 2),
                rendered={
                    name: rendered_size(page.width_pt, page.height_pt, preset)
                    for name, preset in pricing.resolution_presets.items()
                },
            )
        )
    return facts


def _model_estimate(
    document: Document,
    facts: list[PageFacts],
    model: ModelPricing,
    pricing: PricingConfig,
    today: dt.date,
) -> ModelCostEstimate:
    price = model.input_per_mtok_usd or 0.0
    token_count: TokenCount = count_tokens(document.full_text, model.tokenizer)

    text_unavailable: str | None = None
    if not document.pages:
        text_unavailable = "the document could not be opened, so no text was available"
    elif not document.full_text.strip():
        text_unavailable = (
            "the document has no text layer and none was recovered by OCR, so a "
            "text-extraction path does not exist for it"
        )

    text_cost = None if text_unavailable else token_count.tokens / 1_000_000 * price

    vision_tokens_by: dict[str, int] = {}
    vision_cost_by: dict[str, float] = {}
    vision_unavailable: str | None = None
    formula = pricing.vision_formulas.get(model.vision_formula or "")

    if not model.supports_vision:
        vision_unavailable = f"{model.display_name} is not configured as a vision model"
    elif formula is None:
        vision_unavailable = (
            f"no vision token formula is configured for {model.display_name}, so image "
            f"tokens cannot be counted"
        )
    elif not facts:
        vision_unavailable = "the document could not be opened, so it has no pages to render"
    elif all(fact.width_pt <= 0 or fact.height_pt <= 0 for fact in facts):
        vision_unavailable = (
            "page dimensions are not determinable for this format without rendering it, "
            "so the number of image tokens per page cannot be computed. This is not a "
            "cost of zero; it is an unknown."
        )
    else:
        for name in pricing.resolution_presets:
            total = sum(vision_tokens(fact.rendered[name], formula) for fact in facts)
            vision_tokens_by[name] = total
            vision_cost_by[name] = total / 1_000_000 * price

    throughput = model.input_tokens_per_second
    text_seconds = token_count.tokens / throughput if throughput and text_cost is not None else None

    age = model.days_since_verified(today)
    return ModelCostEstimate(
        model_id=model.id,
        display_name=model.display_name,
        provider=model.provider,
        input_per_mtok_usd=price,
        last_verified=model.last_verified,
        days_since_verified=age,
        is_stale=age is None or age > pricing.staleness_warn_days,
        text_tokens=token_count.tokens,
        text_token_fidelity=token_count.fidelity,
        text_token_note=token_count.note,
        text_path_input_usd=text_cost,
        text_path_unavailable_reason=text_unavailable,
        vision_tokens_by_resolution=vision_tokens_by,
        vision_input_usd_by_resolution=vision_cost_by,
        vision_path_unavailable_reason=vision_unavailable,
        text_path_seconds=round(text_seconds, 2) if text_seconds else None,
        vision_formula=model.vision_formula,
    )


class UnknownModelError(ValueError):
    """A model was asked for by name and is not in the pricing config."""


def resolve_models(pricing: PricingConfig, wanted: Sequence[str] | None) -> list[ModelPricing]:
    """The models to compare. Everything priced and enabled, unless names are given."""
    if not wanted:
        return pricing.usable_models
    by_id = {m.id: m for m in pricing.models}
    chosen: list[ModelPricing] = []
    unknown: list[str] = []
    unpriced: list[str] = []
    for name in wanted:
        model = by_id.get(name)
        if model is None:
            unknown.append(name)
        elif not model.is_priced:
            unpriced.append(name)
        else:
            chosen.append(model)
    problems = []
    if unknown:
        problems.append("not in pricing.yaml: " + ", ".join(unknown))
    if unpriced:
        problems.append("present but carries no price: " + ", ".join(unpriced))
    if problems:
        raise UnknownModelError("; ".join(problems))
    return chosen


def estimate_document(
    document: Document,
    pricing: PricingConfig,
    today: dt.date | None = None,
    models: Sequence[ModelPricing] | None = None,
) -> DocumentCostEstimate:
    now = today or dt.date.today()
    facts = _page_facts(document, pricing)
    coverages = [f.text_coverage_pct for f in facts]

    return DocumentCostEstimate(
        path=document.path,
        page_count=document.page_count,
        page_count_known=document.page_count_known,
        has_text_layer=document.has_text_layer,
        mean_text_coverage_pct=round(sum(coverages) / len(coverages), 2) if coverages else 0.0,
        pages=facts,
        models=[
            _model_estimate(document, facts, model, pricing, now)
            for model in (models if models is not None else pricing.usable_models)
        ],
    )


def _extrapolate(
    estimates: list[DocumentCostEstimate], monthly_volume: int, resolution: str
) -> VolumeExtrapolation:
    text_values = [e.cheapest_text_path_usd() for e in estimates]
    text_present = [v for v in text_values if v is not None]
    vision_values = [e.cheapest_vision_path_usd(resolution) for e in estimates]
    vision_present = [v for v in vision_values if v is not None]

    mean_text = sum(text_present) / len(text_present) if text_present else None
    mean_vision = sum(vision_present) / len(vision_present) if vision_present else None

    return VolumeExtrapolation(
        monthly_volume=monthly_volume,
        documents_measured=len(estimates),
        mean_text_path_usd=mean_text,
        mean_vision_path_usd=mean_vision,
        monthly_text_usd=mean_text * monthly_volume if mean_text is not None else None,
        monthly_vision_usd=mean_vision * monthly_volume if mean_vision is not None else None,
        annual_text_usd=mean_text * monthly_volume * 12 if mean_text is not None else None,
        annual_vision_usd=mean_vision * monthly_volume * 12 if mean_vision is not None else None,
        basis=(
            f"Mean cost per document across the {count(len(estimates), 'document')} audited, using "
            f"the cheapest priced model for each, multiplied by the stated monthly volume. "
            f"This assumes the audited sample is representative of the wider set; if it is "
            f"not, the extrapolation is not either."
        ),
    )


def estimate_folder(
    documents: list[Document],
    pricing: PricingConfig,
    headline_resolution: str = "medium",
    monthly_volume: int | None = None,
    today: dt.date | None = None,
    select_models: Sequence[str] | None = None,
) -> FolderCostEstimate:
    chosen = resolve_models(pricing, select_models)
    resolutions = list(pricing.resolution_presets)
    if headline_resolution not in resolutions and resolutions:
        headline_resolution = resolutions[0]

    fx = pricing.currency.usd_to_gbp
    use_fx = pricing.currency.report_in.upper() != "USD" and fx.rate is not None

    estimate = FolderCostEstimate(
        currency=pricing.currency.report_in.upper() if use_fx else "USD",
        usd_to_report_rate=fx.rate if use_fx else None,
        headline_resolution=headline_resolution,
        resolutions=resolutions,
        documents=[estimate_document(d, pricing, today, chosen) for d in documents],
    )
    if monthly_volume:
        estimate.volume = _extrapolate(estimate.documents, monthly_volume, headline_resolution)
    return estimate
