"""Checksum and format validators.

A regex alone produces far too many false positives on business documents, which
are full of reference numbers that look like identifiers. These run after the
regex and discard anything that fails, so the counts in the report mean
something.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable

__all__ = ["VALIDATORS", "iban_mod97", "luhn", "validate", "vat_mod97"]

# Neither of these letters may start a National Insurance prefix, and a handful
# of two-letter pairs are administratively reserved.
_NI_INVALID_FIRST = set("DFIQUV")
_NI_INVALID_SECOND = set("DFIOQUV")
_NI_RESERVED_PAIRS = {"BG", "GB", "NK", "KN", "TN", "NT", "ZZ"}

_UK_POSTCODE = re.compile(
    r"^(GIR ?0AA|[A-PR-UWYZ]([0-9]{1,2}|([A-HK-Y][0-9]([0-9ABEHMNPRV-Y])?)"
    r"|[0-9][A-HJKPS-UW]) ?[0-9][ABD-HJLNP-UW-Z]{2})$",
    re.IGNORECASE,
)

_VALID_UK_PHONE_PREFIXES = ("01", "02", "03", "05", "07", "08", "09")


def _digits(value: str) -> str:
    return "".join(c for c in value if c.isdigit())


def luhn(value: str) -> bool:
    """The Luhn checksum used by payment cards."""
    digits = _digits(value)
    if not 12 <= len(digits) <= 19:
        return False
    total = 0
    for index, char in enumerate(reversed(digits)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def iban_mod97(value: str) -> bool:
    """ISO 13616: move the first four characters to the end, then mod 97 must be 1."""
    cleaned = "".join(value.split()).upper()
    if not 15 <= len(cleaned) <= 34 or not cleaned[:2].isalpha() or not cleaned[2:4].isdigit():
        return False
    rearranged = cleaned[4:] + cleaned[:4]
    converted = ""
    for char in rearranged:
        if char.isdigit():
            converted += char
        elif char.isalpha():
            converted += str(ord(char) - 55)
        else:
            return False
    try:
        return int(converted) % 97 == 1
    except ValueError:
        return False


def ni_prefix(value: str) -> bool:
    cleaned = "".join(value.split()).upper()
    if len(cleaned) < 2:
        return False
    first, second = cleaned[0], cleaned[1]
    if first in _NI_INVALID_FIRST or second in _NI_INVALID_SECOND:
        return False
    return cleaned[:2] not in _NI_RESERVED_PAIRS


def vat_mod97(value: str) -> bool:
    """UK VAT: both the original mod-97 rule and the later 9755 variant are accepted."""
    digits = _digits(value)
    if len(digits) not in (9, 12):
        return False
    body, check = digits[:7], int(digits[7:9])
    weighted = sum(int(d) * w for d, w in zip(body, (8, 7, 6, 5, 4, 3, 2), strict=True))
    return (weighted + check) % 97 == 0 or (weighted + 55 + check) % 97 == 0


def sort_code(value: str) -> bool:
    digits = _digits(value)
    # Six digits, and not an obviously fake run like 000000 or 111111.
    return len(digits) == 6 and len(set(digits)) > 1


def uk_postcode(value: str) -> bool:
    return bool(_UK_POSTCODE.match(value.strip()))


def uk_phone(value: str) -> bool:
    cleaned = "".join(value.split()).replace("-", "")
    if cleaned.startswith("+44"):
        cleaned = "0" + cleaned[3:]
    digits = _digits(cleaned)
    if len(digits) not in (10, 11):
        return False
    return digits.startswith(_VALID_UK_PHONE_PREFIXES)


def plausible_dob(value: str) -> bool:
    """A date that could belong to a living person."""
    today = dt.date.today()
    candidates = (
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%Y",
        "%d/%m/%y",
        "%d %b %Y",
        "%d %B %Y",
    )
    text = " ".join(value.split())
    for fmt in candidates:
        try:
            parsed = dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        age = (today - parsed).days / 365.25
        return 0 <= age <= 120
    return False


VALIDATORS: dict[str, Callable[[str], bool]] = {
    "luhn": luhn,
    "iban_mod97": iban_mod97,
    "ni_prefix": ni_prefix,
    "vat_mod97": vat_mod97,
    "sort_code": sort_code,
    "uk_postcode": uk_postcode,
    "uk_phone": uk_phone,
    "plausible_dob": plausible_dob,
}


def validate(value: str, names: list[str]) -> tuple[bool, list[str]]:
    """Run the named validators. Returns (all passed, names that passed)."""
    passed: list[str] = []
    for name in names:
        checker = VALIDATORS.get(name)
        if checker is None:
            continue
        if not checker(value):
            return False, passed
        passed.append(name)
    return True, passed
