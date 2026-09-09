"""Configuration schema, staleness and the rules it refuses to bend."""

from __future__ import annotations

import datetime as dt

import pytest
import yaml
from pydantic import ValidationError

from complydoc.config.loader import ConfigError, check_staleness, load_config
from complydoc.config.schema import (
    PricingConfig,
    ReadinessConfig,
    ScoringConfig,
    SignalConfig,
    Threshold,
)
from tests.helpers import FIXTURES


def test_shipped_config_loads(config):
    assert config.pricing.schema_version == 1
    assert config.readiness.signals
    assert config.sensitive.categories
    assert len(config.digest) == 16


def test_every_signal_in_config_has_a_registered_signal(config):
    from complydoc.readiness.registry import all_signals

    registered = {s.id for s in all_signals()}
    configured = set(config.readiness.signals)
    assert configured == registered, (
        f"config and code disagree: only in config {configured - registered}, "
        f"only in code {registered - configured}"
    )


def test_every_category_names_a_registered_detector(config):
    from complydoc.sensitive.registry import all_detectors

    registered = {d.id for d in all_detectors()}
    for name, category in config.sensitive.categories.items():
        assert category.detector in registered, f"{name} names unknown detector"


def test_scoring_cannot_hide_its_weights():
    """A score whose weights are not printed is exactly what this tool refuses."""
    with pytest.raises(ValidationError, match="print_weights_in_report"):
        ScoringConfig(enabled=True, print_weights_in_report=False)


def test_threshold_requires_exactly_one_operator():
    with pytest.raises(ValidationError):
        Threshold()
    with pytest.raises(ValidationError):
        Threshold(gte=1, lt=5)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(90, "good"), (50, "fair"), (10, "poor"), (None, None)],
)
def test_signal_rating_picks_the_first_match(value, expected):
    settings = SignalConfig(
        thresholds={
            "good": Threshold(gte=60),
            "fair": Threshold(gte=25),
            "poor": Threshold(lt=25),
        }
    )
    assert settings.rate(value) == expected


def test_boolean_thresholds_match():
    settings = SignalConfig(thresholds={"good": Threshold(eq=False), "poor": Threshold(eq=True)})
    assert settings.rate(False) == "good"
    assert settings.rate(True) == "poor"


def test_unpriced_models_are_excluded_from_costing(config):
    usable = {m.id for m in config.pricing.usable_models}
    for model in config.pricing.models:
        if not model.enabled or model.input_per_mtok_usd is None:
            assert model.id not in usable


def test_a_never_verified_price_always_warns(config):
    """A missing date is treated as maximally stale, not as fine."""
    raw = yaml.safe_load((FIXTURES.parent.parent / "src/complydoc/config/pricing.yaml").read_text())
    raw["models"][0]["last_verified"] = None
    pricing = PricingConfig.model_validate(raw)
    warnings = check_staleness(pricing, dt.date(2026, 6, 25))
    assert any(w.never_verified for w in warnings)
    assert "never verified" in next(w for w in warnings if w.never_verified).message


def test_staleness_uses_the_configured_threshold(config):
    verified = config.pricing.models[0].last_verified
    assert verified is not None
    just_inside = verified + dt.timedelta(days=config.pricing.staleness_warn_days)
    just_outside = just_inside + dt.timedelta(days=1)
    assert not check_staleness(config.pricing, just_inside)
    assert check_staleness(config.pricing, just_outside)


def test_unknown_vision_formula_is_rejected(config):
    raw = yaml.safe_load((FIXTURES.parent.parent / "src/complydoc/config/pricing.yaml").read_text())
    raw["models"][0]["vision_formula"] = "does-not-exist"
    with pytest.raises(ValidationError, match="unknown vision_formula"):
        PricingConfig.model_validate(raw)


def test_missing_config_directory_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path)


def test_unknown_config_key_is_rejected():
    with pytest.raises(ValidationError):
        ReadinessConfig.model_validate(
            {"schema_version": 1, "scoring": {}, "signals": {}, "surprise": 1}
        )
