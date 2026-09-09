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
Direction = Literal["higher_is_easier", "lower_is_easier"]
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
    input_per_mtok_usd: float | None = None
    output_per_mtok_usd: float | None = None
    supports_vision: bool = True
    vision_formula: str | None = None
    tokenizer: TokenizerSpec
    last_verified: dt.date | None = None
    source_url: str | None = None
    notes: str | None = None

    @property
    def is_priced(self) -> bool:
        return self.input_per_mtok_usd is not None

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


class PricingConfig(_Base):
    schema_version: int
    staleness_warn_days: int = 90
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
# difficulty.yaml
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
    direction: Direction = "higher_is_easier"
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


class DifficultyConfig(_Base):
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
    difficulty: DifficultyConfig
    sensitive: SensitiveConfig
    source_dir: str
    digest: str
    """SHA-256 over the three raw files, so two runs can be compared honestly."""
