"""The single point at which a detected value can become readable text.

Every reported hit goes through `render`. Nothing else in complydoc turns a span
back into characters. That is the whole design: a report cannot leak a bank
account number by accident, because the code path that would print one does not
exist anywhere else.

Masking is the default. `--reveal` is honoured only for categories not listed
under `masking.never_reveal`, and any report produced with it is stamped.
"""

from __future__ import annotations

from complydoc.config.schema import MaskingConfig

__all__ = ["mask_value", "render", "reveal_allowed"]


def reveal_allowed(category: str, config: MaskingConfig) -> bool:
    """Whether --reveal may show this category at all."""
    return category not in config.never_reveal


def mask_value(value: str, config: MaskingConfig) -> str:
    """Replace every character except the last few, keeping separators visible.

    Separators are kept because they make the shape of the identifier legible —
    a masked sort code should still look like a sort code — without disclosing
    anything about the value.
    """
    tail = max(0, config.reveal_tail_chars)
    significant = [i for i, c in enumerate(value) if c.isalnum()]

    if len(significant) <= tail:
        # Too short to show any of it without showing effectively all of it.
        keep: set[int] = set()
    else:
        keep = set(significant[-tail:]) if tail else set()

    def shown(index: int, char: str) -> str:
        if char.isalnum():
            return char if index in keep else config.mask_char
        # Separators stay so the shape remains legible, but line breaks and other
        # control characters are flattened to a space: a masked value goes into a
        # table cell and must never carry layout of its own.
        return char if char.isprintable() else " "

    return "".join(shown(i, c) for i, c in enumerate(value))


def render(
    value: str, category: str, config: MaskingConfig, reveal: bool
) -> tuple[str, str | None]:
    """Return (masked, revealed). `revealed` is None unless it is both asked for
    and permitted for this category."""
    masked = mask_value(value, config)
    if reveal and reveal_allowed(category, config):
        # Collapse whitespace so a revealed value is still a single line.
        return masked, " ".join(value.split())
    return masked, None
