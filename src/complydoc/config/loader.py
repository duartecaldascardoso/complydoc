"""Load, validate and age-check the configuration files."""

from __future__ import annotations

import datetime as dt
import hashlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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
    wanted = [p.lower() for p in pricing.compare.providers]
    if pricing.compare.top_up_from_catalogue:
        merged = _select(merged, pricing.compare.per_provider, wanted)
    return pricing.model_copy(update={"models": merged})


_RECENT_MONTHS = 18
"""How far back the comparison reaches for a model.

Price alone would put a two-year-old model at the cheap end of every ladder and
a long-retired premium one at the top. Both are real prices; neither is what
anyone is choosing between today.
"""


def _bare(model_id: str) -> str:
    """A model id without the provider prefix some entries carry."""
    return model_id.rsplit("/", 1)[-1]


def _select(
    models: list[ModelPricing], per_provider: int, providers: list[str]
) -> list[ModelPricing]:
    """Choose the comparison: `per_provider` models spread across each price range.

    Every model is a candidate, curated or catalogue, so the ladder is chosen on
    its merits rather than around whichever entries happened to be written down
    first. A verified price wins a tie, because it is the one somebody checked.
    """
    from complydoc.cost.price_table import family_of, released_on

    candidates: dict[str, list[ModelPricing]] = defaultdict(list)
    for model in models:
        if providers and model.provider.lower() not in providers:
            continue
        if model.is_priced and model.supports_vision:
            candidates[model.provider].append(model)

    chosen: set[str] = set()
    for available in candidates.values():
        chosen.update(m.id for m in _spread(available, per_provider, family_of, released_on))

    return [m.model_copy(update={"enabled": m.id in chosen}) for m in models]


def _spread(
    models: list[ModelPricing],
    wanted: int,
    family_of: Callable[[str], str],
    released: Callable[[str], dt.date | None],
) -> list[ModelPricing]:
    """`wanted` models spread across the price range of what is current.

    Reduced three times before spreading: to what was released recently enough
    to be a live choice, then to one per family so a model stamped with its
    release date does not appear beside itself, then to one per price so five
    versions of one tier cannot fill the whole comparison.
    """
    if not models:
        return []

    cutoff = dt.date.today() - dt.timedelta(days=int(_RECENT_MONTHS * 30.5))
    current = [m for m in models if (released(m.id) or dt.date.min) >= cutoff]
    # A provider whose whole line predates the cutoff still gets a comparison,
    # built from the newest it has, rather than dropping out of the report.
    if len(current) < wanted:
        by_age = sorted(models, key=lambda m: released(m.id) or dt.date.min, reverse=True)
        current = by_age[: max(wanted, len(current))]

    def preference(model: ModelPricing) -> tuple[Any, ...]:
        # Newest first; a verified price breaks a tie, being the one checked.
        return (
            released(model.id) or dt.date.min,
            model.price_source == "verified",
            model.id,
        )

    ranked = sorted(current, key=preference, reverse=True)

    seen: set[str] = set()
    by_family: list[ModelPricing] = []
    for model in ranked:
        key = family_of(_bare(model.id))
        if key in seen:
            continue
        seen.add(key)
        by_family.append(model)

    by_price: dict[float, ModelPricing] = {}
    for model in by_family:
        by_price.setdefault(m_price(model), model)

    ladder = sorted(by_price.values(), key=m_price)
    ladder = _without_outliers(ladder)
    if wanted >= len(ladder):
        return ladder
    if wanted == 1:
        return [ladder[0]]
    # Evenly spaced, always keeping both ends: the cheapest option and the
    # dearest are the two a reader most wants to see.
    step = (len(ladder) - 1) / (wanted - 1)
    return [ladder[i] for i in sorted({round(i * step) for i in range(wanted)})]


_OUTLIER_MULTIPLE = 8.0
"""How far above the middle of a provider's range a price may sit and still be
part of the comparison.

One model at a hundred and fifty dollars a million tokens is a real price and a
useless bar: it flattens every other model on the chart to nothing, and nobody
choosing how to read invoices is choosing it.
"""


def _without_outliers(ladder: list[ModelPricing]) -> list[ModelPricing]:
    if len(ladder) < 3:
        return ladder
    middle = m_price(ladder[len(ladder) // 2])
    if middle <= 0:
        return ladder
    kept = [m for m in ladder if m_price(m) <= middle * _OUTLIER_MULTIPLE]
    return kept if len(kept) >= 2 else ladder


def m_price(model: ModelPricing) -> float:
    return model.input_per_mtok_usd or 0.0


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
