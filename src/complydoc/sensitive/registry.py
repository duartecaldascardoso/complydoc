"""Detector registry.

Adding a detector means adding one file under `detectors/` with an `@detector`
decorated class, and pointing a category at it by name in sensitive.yaml.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Final, TypeVar

from complydoc.sensitive.base import Detector

__all__ = ["DetectorUnavailableError", "all_detectors", "detector", "detector_by_id"]

_DETECTORS: Final[dict[str, Detector]] = {}
_discovered = False

T = TypeVar("T", bound=type)


class DetectorUnavailableError(RuntimeError):
    """A detector cannot run — usually an optional model that is not installed.

    Raised rather than returning nothing, so the scan reports the category as
    unscanned instead of reporting a count of zero. Those two things mean very
    different things to someone assessing breach risk.
    """


def detector(cls: T) -> T:
    instance = cls()
    if not isinstance(instance, Detector):  # pragma: no cover - programming error
        raise TypeError(f"{cls.__name__} does not satisfy the Detector protocol")
    if instance.id in _DETECTORS:
        raise ValueError(f"duplicate detector id {instance.id!r}")
    _DETECTORS[instance.id] = instance
    return cls


def _discover() -> None:
    global _discovered
    if _discovered:
        return
    _discovered = True
    package = importlib.import_module("complydoc.sensitive.detectors")
    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"complydoc.sensitive.detectors.{info.name}")


def all_detectors() -> list[Detector]:
    _discover()
    return list(_DETECTORS.values())


def detector_by_id(detector_id: str) -> Detector | None:
    _discover()
    return _DETECTORS.get(detector_id)
