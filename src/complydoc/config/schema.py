"""Pydantic models for the three configuration files.

Everything a reader might want to disagree with — a price, a token formula, a
signal weight, a rating threshold, a detection pattern — lives in YAML and is
validated here. No number that appears in a report is hardcoded in Python.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Rating = Literal["good", "fair", "poor"]
Severity = Literal["low", "medium", "high"]
Direction = Literal["higher_is_better", "lower_is_better"]
Fidelity = Literal["exact", "approximate"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------
# pricing.yaml
# --------------------------------------------------------------------------


class TiledVisionFormula(_Base):
    """Providers that split an image into fixed tiles and charge per tile."""

    kind: Literal["tiled"]
    base_tokens: int
    tile_tokens: int
    tile_px: int
    max_short_side_px: int
    max_long_side_px: int
    notes: str | None = None


class WidthHeightVisionFormula(_Base):
    """Providers that charge on raw pixel area: tokens = (w * h) / divisor."""

    kind: Literal["width_height"]
    divisor: float
    cap_tokens: int | None = None
    notes: str | None = None


class FlatVisionFormula(_Base):
    """Providers that charge a flat count per image below a size threshold."""

    kind: Literal["flat_per_image"]
    tokens_per_image: int
    tile_above_px: int | None = None
    tile_tokens: int | None = None
    notes: str | None = None


VisionFormula = Annotated[
    TiledVisionFormula | WidthHeightVisionFormula | FlatVisionFormula,
    Field(discriminator="kind"),
]


class ResolutionPreset(_Base):
    long_edge_px: int


class TokenizerSpec(_Base):
    encoding: str
    fidelity: Fidelity
    approximation_note: str | None = None
    approximate_ratio: float = 1.0
    """Multiplier applied to the encoding's count when fidelity is approximate."""

    @model_validator(mode="after")
    def _note_required_when_approximate(self) -> TokenizerSpec:
        if self.fidelity == "approximate" and not self.approximation_note:
            raise ValueError("approximation_note is required when fidelity is 'approximate'")
        return self


class ModelPricing(_Base):
    id: str
    provider: str
    display_name: str
    enabled: bool = True

    @model_validator(mode="after")
    def _named_not_identified(self) -> ModelPricing:
        """A model that carries its own id as its name borrows the catalogue's.

        An entry written in a hurry gets `display_name` equal to `id`, and the
        chart then reads `zai/glm-5.3-flash` beside `Claude Sonnet 5`. The
        catalogue almost always knows what the provider calls it.
        """
        if self.display_name == self.id:
            from complydoc.cost.price_table import display_name_for

            better = display_name_for(self.id)
            if better:
                object.__setattr__(self, "display_name", better)
        return self

    input_per_mtok_usd: float | None = None
    output_per_mtok_usd: float | None = None
    batch_input_per_mtok_usd: float | None = None
    """Input price on the provider's batch endpoint, where it publishes one.

    Never inferred from the usual half-price convention. A discount nobody can
    check does not belong in a budget, so a model without a published batch
    price simply has none here and the report says so.
    """
    supports_vision: bool = True
    vision_formula: str | None = None
    tokenizer: TokenizerSpec
    input_tokens_per_second: float | None = None
    """Observed prefill throughput, for estimating how long a document takes.

    Left unset because complydoc cannot measure it offline and will not invent it.
    Set it from your own benchmark and the report will estimate processing time;
    leave it and the report says the time was not estimated.
    """
    last_verified: dt.date | None = None
    source_url: str | None = None
    notes: str | None = None
    price_source: Literal["verified", "imported"] = "verified"
    """Where the number came from.

    "verified" means a person read it off the provider's own page and stamped
    `last_verified`. "imported" means it was taken from a maintained third-party
    table on `imported_on` and nobody has checked it since. The report keeps the
    two apart rather than presenting an import as a verification.
    """
    imported_on: dt.date | None = None

    @property
    def is_priced(self) -> bool:
        return self.input_per_mtok_usd is not None

    @property
    def has_batch_price(self) -> bool:
        return self.batch_input_per_mtok_usd is not None

    def days_since_verified(self, today: dt.date) -> int | None:
        if self.last_verified is None:
            return None
        return (today - self.last_verified).days


class FxRate(_Base):
    rate: float | None = None
    """None means no verified rate is configured; costs stay in USD."""

    last_verified: dt.date | None = None
    source_url: str | None = None


class CurrencyConfig(_Base):
    report_in: str = "GBP"
    usd_to_gbp: FxRate


class CompareConfig(_Base):
    """How many models the report compares, and how they are chosen.

    The curated entries are always in. Below `per_provider`, each provider is
    topped up from the vendored catalogue with its most recently released models
    that take images, so a refreshed catalogue brings a refreshed comparison
    rather than a file somebody has to remember to edit.
    """

    providers: list[str] = []
    """Which providers the default comparison covers. Empty means all of them."""
    per_provider: int = 4
    """How many models each provider contributes, spread across its price range.

    Not the four newest — those tend to cost about the same as each other, and
    four figures within a few cents say nothing. Spread across the range they
    give the trade you are actually choosing between: Anthropic contributes
    haiku, sonnet, opus and fable rather than four flavours of opus.
    """
    top_up_from_catalogue: bool = True
    headline_model: str = "claude-sonnet-5"
    """The model the summary quotes when it has to name one number.

    The report compares a dozen models, but the figure on the front page has to
    be a figure, and that means picking one. The cheapest in the comparison was
    the wrong pick: it is whichever small model happened to be cheapest that
    week, so the headline moved for reasons that had nothing to do with the
    folder, and it flattered the estimate. A mid-range model in wide use is what
    someone is actually likely to run, and it stays put between refreshes of the
    catalogue.

    Falls back to the cheapest priced model in the comparison when this one is
    not among them, and the report says which it used either way.
    """


class PricingConfig(_Base):
    schema_version: int
    staleness_warn_days: int = 90
    compare: CompareConfig = CompareConfig()
    currency: CurrencyConfig
    vision_formulas: dict[str, VisionFormula]
    resolution_presets: dict[str, ResolutionPreset]
    models: list[ModelPricing]

    @model_validator(mode="after")
    def _formulas_resolve(self) -> PricingConfig:
        for model in self.models:
            key = model.vision_formula
            if key is not None and key not in self.vision_formulas:
                raise ValueError(f"model {model.id!r} references unknown vision_formula {key!r}")
        return self

    def model_by_id(self, model_id: str) -> ModelPricing | None:
        return next((m for m in self.models if m.id == model_id), None)

    @property
    def usable_models(self) -> list[ModelPricing]:
        """Models that are switched on and carry a price we can actually multiply."""
        return [m for m in self.models if m.enabled and m.is_priced]


# --------------------------------------------------------------------------
# readiness.yaml
# --------------------------------------------------------------------------


class Threshold(_Base):
    """A single comparison. Exactly one operator must be set."""

    gte: float | None = None
    gt: float | None = None
    lte: float | None = None
    lt: float | None = None
    eq: float | bool | str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Threshold:
        set_ops = [op for op in (self.gte, self.gt, self.lte, self.lt, self.eq) if op is not None]
        if len(set_ops) != 1:
            raise ValueError("a threshold must set exactly one of gte/gt/lte/lt/eq")
        return self

    def matches(self, value: float | bool | str | None) -> bool:
        if value is None:
            return False
        if self.eq is not None:
            return bool(value == self.eq)
        if isinstance(value, str):
            return False
        numeric = float(value)
        if self.gte is not None:
            return numeric >= self.gte
        if self.gt is not None:
            return numeric > self.gt
        if self.lte is not None:
            return numeric <= self.lte
        if self.lt is not None:
            return numeric < self.lt
        return False


class SignalConfig(_Base):
    enabled: bool = True
    weight: float = 0.0
    direction: Direction = "higher_is_better"
    thresholds: dict[Rating, Threshold] = Field(default_factory=dict)
    why: str | None = None
    """Overrides the default explanation carried by the signal module."""

    def rate(self, value: float | bool | str | None) -> Rating | None:
        """First matching rating wins, checked good then fair then poor."""
        order: tuple[Rating, ...] = ("good", "fair", "poor")
        for rating in order:
            threshold = self.thresholds.get(rating)
            if threshold is not None and threshold.matches(value):
                return rating
        return None


def _default_rating_points() -> dict[Rating, float]:
    return {"good": 1.0, "fair": 0.5, "poor": 0.0}


class ScoringConfig(_Base):
    enabled: bool = True
    method: Literal["weighted_sum"] = "weighted_sum"
    show_breakdown_by_default: bool = True
    print_weights_in_report: bool = True
    rating_points: dict[Rating, float] = Field(default_factory=_default_rating_points)

    @model_validator(mode="after")
    def _weights_must_be_visible(self) -> ScoringConfig:
        if self.enabled and not self.print_weights_in_report:
            raise ValueError(
                "scoring.enabled requires print_weights_in_report: true — a score whose "
                "weights are not shown in the report is exactly what this tool refuses to emit"
            )
        return self


class ReadinessConfig(_Base):
    schema_version: int
    scoring: ScoringConfig
    signals: dict[str, SignalConfig]

    def for_signal(self, signal_id: str) -> SignalConfig | None:
        return self.signals.get(signal_id)


# --------------------------------------------------------------------------
# sensitive.yaml
# --------------------------------------------------------------------------


class MaskingConfig(_Base):
    reveal_tail_chars: int = 4
    mask_char: str = "•"
    never_reveal: list[str] = Field(default_factory=list)
    """Categories that stay masked even when --reveal is passed."""


class NerModelSpec(_Base):
    name: str
    version: str | None = None
    entity_labels: list[str]


class CategoryConfig(_Base):
    enabled: bool = True
    label: str
    region: str = "international"
    """Which jurisdiction the identifier belongs to, shown in the report."""
    detector: str
    severity: Severity = "medium"
    patterns: list[str] = Field(default_factory=list)
    """Patterns distinctive enough to report on their own."""
    context_patterns: list[str] = Field(default_factory=list)
    """Patterns too generic to stand alone — a bare run of digits, say. A hit is
    only reported when one of `context_terms` appears within
    `context_window_chars` of it."""
    validators: list[str] = Field(default_factory=list)
    context_terms: list[str] = Field(default_factory=list)
    context_window_chars: int = 60
    min_confidence: float = 0.0
    gdpr_note: str | None = None
    model: NerModelSpec | None = None


class SensitiveConfig(_Base):
    schema_version: int
    masking: MaskingConfig
    categories: dict[str, CategoryConfig]

    @property
    def enabled_categories(self) -> dict[str, CategoryConfig]:
        return {k: v for k, v in self.categories.items() if v.enabled}


class Config(_Base):
    """The three files, loaded together."""

    pricing: PricingConfig
    readiness: ReadinessConfig
    sensitive: SensitiveConfig
    source_dir: str
    digest: str
    """SHA-256 over the three raw files, so two runs can be compared honestly."""
