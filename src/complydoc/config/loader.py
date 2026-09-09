"""Load, validate and age-check the configuration files."""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from complydoc.config.schema import (
    Config,
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
            pricing=PricingConfig.model_validate(parsed["pricing.yaml"]),
            readiness=ReadinessConfig.model_validate(parsed["readiness.yaml"]),
            sensitive=SensitiveConfig.model_validate(parsed["sensitive.yaml"]),
            source_dir=str(directory),
            digest=digest,
        )
    except ValueError as exc:
        raise ConfigError(f"configuration in {directory} is invalid:\n{exc}") from exc


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
