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


# --- other jurisdictions ---------------------------------------------------


def _weighted_mod(digits: str, weights: tuple[int, ...], modulus: int) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % modulus


def us_ssn(value: str) -> bool:
    """US Social Security number, by the SSA's published exclusions."""
    digits = _digits(value)
    if len(digits) != 9:
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area in {"000", "666"} or area.startswith("9"):
        return False
    return group != "00" and serial != "0000"


def us_ein(value: str) -> bool:
    digits = _digits(value)
    # Only the shape and a valid campus prefix; the EIN carries no checksum.
    return len(digits) == 9 and digits[:2] not in {"00", "07", "08", "09", "17", "18", "19"}


def aba_routing(value: str) -> bool:
    """US bank routing number, ABA checksum."""
    digits = _digits(value)
    if len(digits) != 9:
        return False
    return _weighted_mod(digits, (3, 7, 1, 3, 7, 1, 3, 7, 1), 10) == 0


def nl_bsn(value: str) -> bool:
    """Dutch citizen number, the eleven-proof."""
    digits = _digits(value)
    if len(digits) != 9 or digits == "0" * 9:
        return False
    total = sum(int(d) * w for d, w in zip(digits, (9, 8, 7, 6, 5, 4, 3, 2, -1), strict=True))
    return total % 11 == 0


def pt_nif(value: str) -> bool:
    """Portuguese tax number, mod-11 check digit."""
    digits = _digits(value)
    if len(digits) != 9 or digits[0] not in "125689":
        return False
    total = sum(int(d) * (9 - i) for i, d in enumerate(digits[:8]))
    check = 11 - (total % 11)
    return int(digits[8]) == (0 if check >= 10 else check)


def es_dni(value: str) -> bool:
    """Spanish DNI or NIE, letter derived from the number mod 23."""
    cleaned = "".join(value.split()).upper().replace("-", "")
    if len(cleaned) != 9:
        return False
    body, letter = cleaned[:8], cleaned[8]
    prefix = {"X": "0", "Y": "1", "Z": "2"}
    if body[0] in prefix:
        body = prefix[body[0]] + body[1:]
    if not body.isdigit() or not letter.isalpha():
        return False
    return "TRWAGMYFPDXBNJZSQVHLCKE"[int(body) % 23] == letter


def ie_pps(value: str) -> bool:
    """Irish PPS number: seven digits, a check letter, optionally a second letter."""
    cleaned = "".join(value.split()).upper()
    if len(cleaned) not in (8, 9) or not cleaned[:7].isdigit():
        return False
    total = sum(int(d) * (8 - i) for i, d in enumerate(cleaned[:7]))
    if len(cleaned) == 9 and cleaned[8].isalpha():
        total += (ord(cleaned[8]) - 64) * 9
    return "WABCDEFGHIJKLMNOPQRSTUV"[total % 23] == cleaned[7]


def fr_nir(value: str) -> bool:
    """French social security number, mod-97 check on the first thirteen digits."""
    cleaned = "".join(value.split()).upper()
    body = cleaned[:13].replace("2A", "19").replace("2B", "18")
    check = cleaned[13:15]
    if not body.isdigit() or not check.isdigit():
        return False
    return int(check) == 97 - (int(body) % 97)


def de_steuer_id(value: str) -> bool:
    """German tax identification number: eleven digits, ISO 7064 check digit."""
    digits = _digits(value)
    if len(digits) != 11:
        return False
    # Exactly one digit repeats in the first ten, which is what distinguishes a
    # real Steuer-ID from an arbitrary eleven-digit run.
    counts = {d: digits[:10].count(d) for d in set(digits[:10])}
    if sorted(counts.values(), reverse=True)[0] not in (2, 3):
        return False
    product = 10
    for digit in digits[:10]:
        total = (int(digit) + product) % 10 or 10
        product = (2 * total) % 11
    check = (11 - product) % 10
    return check == int(digits[10])


def eu_vat(value: str) -> bool:
    """Any EU or UK VAT number by country prefix and length."""
    cleaned = "".join(value.split()).upper().replace("-", "")
    if len(cleaned) < 4 or not cleaned[:2].isalpha():
        return False
    country, body = cleaned[:2], cleaned[2:]
    lengths = {
        "AT": (9,),
        "BE": (10,),
        "BG": (9, 10),
        "CY": (9,),
        "CZ": (8, 9, 10),
        "DE": (9,),
        "DK": (8,),
        "EE": (9,),
        "EL": (9,),
        "ES": (9,),
        "FI": (8,),
        "FR": (11,),
        "GB": (9, 12),
        "HR": (11,),
        "HU": (8,),
        "IE": (8, 9),
        "IT": (11,),
        "LT": (9, 12),
        "LU": (8,),
        "LV": (11,),
        "MT": (8,),
        "NL": (12,),
        "PL": (10,),
        "PT": (9,),
        "RO": tuple(range(2, 11)),
        "SE": (12,),
        "SI": (8,),
        "SK": (10,),
    }
    if country not in lengths or len(body) not in lengths[country]:
        return False
    if country == "GB":
        return vat_mod97(body)
    return any(c.isdigit() for c in body)


VALIDATORS: dict[str, Callable[[str], bool]] = {
    "luhn": luhn,
    "iban_mod97": iban_mod97,
    "ni_prefix": ni_prefix,
    "vat_mod97": vat_mod97,
    "sort_code": sort_code,
    "uk_postcode": uk_postcode,
    "uk_phone": uk_phone,
    "plausible_dob": plausible_dob,
    "us_ssn": us_ssn,
    "us_ein": us_ein,
    "aba_routing": aba_routing,
    "nl_bsn": nl_bsn,
    "pt_nif": pt_nif,
    "es_dni": es_dni,
    "ie_pps": ie_pps,
    "fr_nir": fr_nir,
    "de_steuer_id": de_steuer_id,
    "eu_vat": eu_vat,
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
