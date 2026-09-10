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
        verified = self.last_verified
        if verified is None:
            return (
                f"{self.entry}: never verified. No last_verified date is set, so this "
                f"figure has no known provenance. Check it and set the date."
            )
        return (
            f"{self.entry}: last verified {verified.isoformat()} "
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


_SPECIALISED = (
    "codex",
    "computer-use",
    "realtime",
    "live",
    "tts",
    "audio",
    "omni",
    "customtools",
    "search",
    "guard",
    "moderation",
    "translate",
    "build",
    "multi-agent",
    # Written to produce code, not to read a page of one.
    "codex",
    "codestral",
    "devstral",
    # Speech, not documents.
    "voxtral",
    "whisper",
)
"""Lines built for something other than reading a document.

A speech model and a computer-use model both have a price and both take images.
Neither is what anyone compares when deciding how to process a folder of
invoices, and either would push out a model that is.
"""


_MARQUES = {
    "anthropic": ("claude",),
    "openai": ("gpt", "o1", "o3", "o4"),
    "gemini": ("gemini", "gemma"),
    "deepseek": ("deepseek",),
    "moonshot": ("kimi",),
    "zai": ("glm",),
    "mistral": ("mistral", "pixtral", "devstral", "codestral", "magistral", "ministral"),
    "xai": ("grok",),
}
_OTHER_PROVIDERS = {
    provider: tuple(
        word for other, words in _MARQUES.items() if other != provider for word in words
    )
    for provider in _MARQUES
}


def _bare(model_id: str) -> str:
    """A model id without the provider prefix some entries carry."""
    return model_id.rsplit("/", 1)[-1]


def _select(
    models: list[ModelPricing], per_provider: int, providers: list[str]
) -> list[ModelPricing]:
    """Choose the comparison: each provider's current line-up.

    One model per product line, the newest cut of it, and the most recently
    released lines first. That is what a reader recognises — Anthropic's haiku,
    sonnet, opus and fable; OpenAI's astra, terra, sol and luna — rather than
    four versions of one model or whatever happened to sit at a price point.

    Text-only models are included. They cannot answer the vision column, and the
    report already says so per model, but they are perfectly real choices for
    reading a text layer, which is the cheapest path and often the chosen one.
    """
    from complydoc.cost.price_table import line_of, released_on

    candidates: dict[str, list[ModelPricing]] = defaultdict(list)
    for model in models:
        if providers and model.provider.lower() not in providers:
            continue
        if not model.is_priced:
            continue
        name = _bare(model.id).lower()
        if any(word in name for word in _SPECIALISED):
            continue
        # A provider that resells another's model files it under its own name.
        # It is the same model at a different price, and listing it as this
        # provider's current line-up misrepresents both of them.
        if any(other in name for other in _OTHER_PROVIDERS.get(model.provider, ())):
            continue
        candidates[model.provider].append(model)

    chosen: set[str] = set()
    for available in candidates.values():
        chosen.update(m.id for m in _current_lineup(available, per_provider, line_of, released_on))

    return [m.model_copy(update={"enabled": m.id in chosen}) for m in models]


def _current_lineup(
    models: list[ModelPricing],
    wanted: int,
    line_of: Callable[[str], str],
    released: Callable[[str], dt.date | None],
) -> list[ModelPricing]:
    """The newest cut of each of the provider's `wanted` newest lines."""
    if not models:
        return []

    def within_line(model: ModelPricing) -> tuple[Any, ...]:
        """Which cut of a line to show: the newest, named as plainly as possible."""
        return (
            released(model.id) or dt.date.min,
            -len(_bare(model.id)),
            model.price_source == "verified",
        )

    newest_of_line: dict[str, ModelPricing] = {}
    for model in sorted(models, key=within_line, reverse=True):
        newest_of_line.setdefault(line_of(_bare(model.id)), model)

    def between_lines(model: ModelPricing) -> tuple[Any, ...]:
        """Which lines to show: the newest, and a named one over the bare family.

        Several lines are released on the same day. When that happens the named
        ones — astra, terra, luna, sol — are what a reader recognises, ahead of
        the plain family name they were all cut from.
        """
        line = line_of(_bare(model.id))
        return (
            released(model.id) or dt.date.min,
            line.count("-"),
            model.price_source == "verified",
            line,
        )

    return sorted(newest_of_line.values(), key=between_lines, reverse=True)[:wanted]


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
