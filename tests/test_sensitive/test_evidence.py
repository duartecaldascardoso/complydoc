"""How strong the case for a finding is.

A number here would claim a precision nobody has: the detectors do not produce
comparable probabilities, and the one that produces none at all used to report
1.0, which put a model's guess level with a passed checksum.

These four tiers say what was actually established. The line they hold is that
a tier is earned by what happened to a finding, not declared by whatever found
it.
"""

from __future__ import annotations

from complydoc.audit import run_audit
from complydoc.sensitive.base import EVIDENCE_ORDER, evidence_of
from tests.helpers import FIXTURES


def matches(config, categories: set[str] | None = None):
    report = run_audit(FIXTURES, config, ("sensitive",), ocr=False)
    return [
        m
        for d in report.documents
        if d.sensitive
        for m in d.sensitive.matches
        if categories is None or m.category in categories
    ]


def test_a_passed_checksum_is_confirmed():
    assert evidence_of("regex", ["luhn"], None) == "confirmed"


def test_a_checksum_outranks_a_nearby_label():
    """Both can be true; the checksum is the stronger of the two."""
    assert evidence_of("regex", ["iban_mod97"], "IBAN") == "confirmed"


def test_a_nearby_label_is_corroboration():
    assert evidence_of("regex", [], "Sort code") == "corroborated"


def test_a_shape_on_its_own_is_only_a_pattern():
    assert evidence_of("regex", [], None) == "pattern"


def test_a_model_naming_something_is_the_weakest_tier():
    """No checksum exists for a person's name, so this is both the best
    evidence available for the category and the least of the four."""
    assert evidence_of("ner", [], None) == "model"
    assert EVIDENCE_ORDER[-1] == "model"


def test_the_model_reports_no_score_rather_than_a_perfect_one(config):
    """The small English pipeline exposes no per-entity score.

    Recording 1.0 was not a measurement, and it is exactly the thing this tool
    refuses to do everywhere else.
    """
    guessed = matches(config, {"person_name", "organisation_name"})
    assert guessed, "the fixtures carry names"
    assert all(m.confidence is None for m in guessed)
    assert all(m.evidence == "model" for m in guessed)


def test_a_checksum_backed_finding_keeps_its_score(config):
    confirmed = [m for m in matches(config) if m.validators_passed]
    assert confirmed
    assert all(m.evidence == "confirmed" for m in confirmed)


def test_every_finding_carries_a_tier(config):
    found = matches(config)
    assert found
    assert all(m.evidence in EVIDENCE_ORDER for m in found)


def test_the_table_breaks_a_severity_tie_by_evidence(config):
    """Two medium findings are not equally worth acting on.

    One passed a checksum and one is a model's guess; the confirmed one should
    not be below the guess just because its filename sorts later.
    """
    from complydoc.report.html_writer import evidence_rank, sensitive_rows, severity_rank

    report = run_audit(FIXTURES, config, ("sensitive",), ocr=False)
    rows = sensitive_rows(report)
    keys = [(severity_rank(m.severity), evidence_rank(m.evidence)) for _, m in rows]
    assert keys == sorted(keys, reverse=True)
