"""Load, validate and age-check the configuration files."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from complydoc.config.schema import (
    Config,
    ModelPricing,
    PricingConfig,
    ReadinessConfig,
    SensitiveConfig,
)

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "ConfigError",
    "StalenessWarning",
    "check_staleness",
    "load_config",
]

DEFAULT_CONFIG_DIR: Final = Path(__file__).parent
_FILENAMES: Final = ("pricing.yaml", "readiness.yaml", "sensitive.yaml")


class ConfigError(RuntimeError):
    """Raised when a configuration file is missing or fails validation."""


@dataclass(frozen=True, slots=True)
class StalenessWarning:
    """One config entry whose verification date is missing or too old.

    Prices move constantly. complydoc would rather shout about an unverified
    number than print it as though it were current.
    """

    entry: str
    """Human-readable identifier, e.g. a model id or 'usd_to_gbp'."""
    last_verified: dt.date | None
    age_days: int | None
    threshold_days: int
    never_verified: bool

    @property
    def message(self) -> str:
        if self.never_verified:
            return (
                f"{self.entry}: never verified. No last_verified date is set, so this "
                f"figure has no known provenance. Check it and set the date."
            )
        return (
            f"{self.entry}: last verified {self.last_verified.isoformat()} "  # type: ignore[union-attr]
            f"({self.age_days} days ago, threshold {self.threshold_days}). "
            f"Re-check before relying on this figure."
        )


def _read(path: Path) -> tuple[str, dict[str, object]]:
    if not path.is_file():
        raise ConfigError(f"configuration file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ConfigError(f"{path.name} must contain a mapping at the top level")
    return raw, parsed


def load_config(config_dir: Path | None = None) -> Config:
    """Load the three config files from `config_dir`, defaulting to the shipped set."""
    directory = (config_dir or DEFAULT_CONFIG_DIR).expanduser().resolve()
    raws: list[str] = []
    parsed: dict[str, dict[str, object]] = {}
    for name in _FILENAMES:
        raw, data = _read(directory / name)
        raws.append(raw)
        parsed[name] = data

    digest = hashlib.sha256("\n".join(raws).encode("utf-8")).hexdigest()[:16]

    try:
        return Config(
            pricing=_with_imported(PricingConfig.model_validate(parsed["pricing.yaml"])),
            readiness=ReadinessConfig.model_validate(parsed["readiness.yaml"]),
            sensitive=SensitiveConfig.model_validate(parsed["sensitive.yaml"]),
            source_dir=str(directory),
            digest=digest,
        )
    except ValueError as exc:
        raise ConfigError(f"configuration in {directory} is invalid:\n{exc}") from exc


def _with_imported(pricing: PricingConfig) -> PricingConfig:
    """Add the vendored table's models behind the curated ones.

    They arrive switched off, so the default comparison is still the short list
    someone has actually checked. What they add is reach: `--model` can name any
    of them, and `complydoc models` can show what there is to name.

    A curated entry always wins. Nothing here overwrites a price a person
    verified with one nobody did.
    """
    from complydoc.cost.price_table import imported_models

    # Curated entries name some models with a provider prefix and the catalogue
    # never does, so kimi-k3 and moonshot/kimi-k3 are one model. Matching on the
    # bare name as well keeps it from being compared against itself.
    known = {model.id for model in pricing.models}
    known |= {model.id.rsplit("/", 1)[-1] for model in pricing.models}
    extra = [model for model in imported_models() if model.id not in known]
    if not extra:
        return pricing
    usable = [
        m for m in extra if m.vision_formula is None or m.vision_formula in pricing.vision_formulas
    ]

    merged = [*pricing.models, *usable]
    if pricing.compare.top_up_from_catalogue:
        merged = _top_up(merged, pricing.compare.per_provider)
    return pricing.model_copy(update={"models": merged})


def _top_up(models: list[ModelPricing], per_provider: int) -> list[ModelPricing]:
    """Bring every provider up to `per_provider` models in the comparison.

    Newest first, and only models that take images: the comparison prices a page
    three ways, and a text-only model cannot answer two of them. A provider with
    nothing left to offer simply stays short.

    The models chosen this way are imported, not verified, and the report says so
    — but a comparison missing two providers entirely was answering less.
    """
    from complydoc.cost.price_table import released_on

    counts = Counter(m.provider for m in models if m.enabled and m.is_priced)
    candidates: dict[str, list[ModelPricing]] = defaultdict(list)
    for model in models:
        if not model.enabled and model.is_priced and model.supports_vision:
            candidates[model.provider].append(model)

    chosen: set[str] = set()
    for provider, available in candidates.items():
        missing = per_provider - counts.get(provider, 0)
        if missing <= 0:
            continue
        # Undated models sort last rather than being taken for ancient ones.
        available.sort(key=lambda m: (released_on(m.id) or dt.date.min, m.id), reverse=True)
        chosen.update(m.id for m in available[:missing])

    if not chosen:
        return models
    return [m.model_copy(update={"enabled": True}) if m.id in chosen else m for m in models]


def check_staleness(pricing: PricingConfig, today: dt.date | None = None) -> list[StalenessWarning]:
    """Every priced entry whose verification date is absent or older than the threshold.

    Disabled models are skipped: an unpriced template nobody is using is not a
    stale number, it is an empty slot.
    """
    now = today or dt.date.today()
    limit = pricing.staleness_warn_days
    warnings: list[StalenessWarning] = []

    for model in pricing.models:
        if not model.enabled:
            continue
        if model.price_source == "imported":
            # Not a verification that went stale — a price that was never
            # claimed to be verified. Telling the reader to "check it and set
            # the date" once per model would bury the run's real limitations
            # under a dozen copies of a fact the provenance entry states once.
            continue
        age = model.days_since_verified(now)
        if age is None:
            warnings.append(
                StalenessWarning(
                    entry=f"model {model.id}",
                    last_verified=None,
                    age_days=None,
                    threshold_days=limit,
                    never_verified=True,
                )
            )
        elif age > limit:
            warnings.append(
                StalenessWarning(
                    entry=f"model {model.id}",
                    last_verified=model.last_verified,
                    age_days=age,
                    threshold_days=limit,
                    never_verified=False,
                )
            )

    fx = pricing.currency.usd_to_gbp
    if pricing.currency.report_in.upper() != "USD":
        if fx.rate is None or fx.last_verified is None:
            warnings.append(
                StalenessWarning(
                    entry="currency.usd_to_gbp",
                    last_verified=None,
                    age_days=None,
                    threshold_days=limit,
                    never_verified=True,
                )
            )
        else:
            age = (now - fx.last_verified).days
            if age > limit:
                warnings.append(
                    StalenessWarning(
                        entry="currency.usd_to_gbp",
                        last_verified=fx.last_verified,
                        age_days=age,
                        threshold_days=limit,
                        never_verified=False,
                    )
                )
    return warnings
