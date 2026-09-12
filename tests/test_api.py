"""The Python API.

    import complydoc as cd
    report = cd.security_audit("~/contracts")

A CLI is used by people; a library is used by other software, which makes the
promises here harder to keep. Two of them are what these tests are mostly
about.

The network guard is process-wide state. Arming it permanently inside a host
application would break every unrelated call in that process, so the library
arms it for the audit and puts the socket module back exactly as it found it —
whatever happens in between.

And the public surface has to be a decision rather than an accident. Everything
reachable from `complydoc` is something callers will depend on and we cannot
then rename, so the set is named explicitly and this checks it has not grown by
mistake.
"""

from __future__ import annotations

import socket

import pytest

import complydoc as cd
from complydoc import offline
from tests.helpers import FIXTURES

SAMPLE = FIXTURES / "sensitive_sample.pdf"


def test_the_public_surface_is_exactly_what_was_promised():
    """A name that appears here by accident is a name we cannot take back."""
    import complydoc.api

    assert set(cd.__all__) == {"__version__", *complydoc.api.__all__}
    expected = {
        # audits
        "full_audit",
        "security_audit",
        "cost_audit",
        "readiness_audit",
        # text out, with the identifiers covered over
        "extract_text",
        "Chunk",
        "TextResult",
        "ExtractionWarning",
        # writing a report somewhere
        "write_html",
        "write_json",
        # configuration, and the errors a caller has to catch by name
        "load_config",
        "ConfigError",
        "UnknownModelError",
        "NetworkAccessError",
        # bringing your own reader
        "register_loader",
        "register_extractor",
        "register_engine",
        "all_extractors",
        "all_engines",
        "supported_extensions",
        "Loader",
        "LoaderError",
        "Extractor",
        "Extraction",
        "PageSource",
        "Engine",
        "Recognised",
        # the vocabulary a loader is written in
        "Document",
        "Page",
        "DocumentFormat",
        "IngestOptions",
        "Rect",
        "TextBlock",
        "sha256_of",
        # options and version
        "AuditOptions",
        "__version__",
    }
    assert set(cd.__all__) == expected
    for name in cd.__all__:
        assert hasattr(cd, name), name


def test_a_security_audit_returns_masked_findings_with_their_evidence():
    report = cd.security_audit(SAMPLE)
    matches = [m for d in report.documents if d.sensitive for m in d.sensitive.matches]
    assert matches
    assert all("•" in m.masked for m in matches)
    assert all(m.revealed is None for m in matches), "a default run reveals nothing"
    assert all(m.evidence for m in matches)


def test_asking_for_one_component_runs_only_that_one():
    """The reason the three narrow entry points exist at all."""
    report = cd.security_audit(SAMPLE)
    assert list(report.run.components_run) == ["sensitive"]
    assert all(d.cost is None and d.readiness is None for d in report.documents)

    priced = cd.cost_audit(SAMPLE)
    assert list(priced.run.components_run) == ["cost"]
    assert all(d.sensitive is None for d in priced.documents)


def test_a_full_audit_carries_the_global_score_and_the_quick_wins():
    report = cd.full_audit(SAMPLE)
    assert report.overall is not None
    assert report.overall.score is not None
    assert report.run.schema_version >= 3, "callers branch on this"


def test_a_string_path_works_as_well_as_a_path():
    """Nobody reaches for pathlib to call one function."""
    assert cd.security_audit(str(SAMPLE)).documents
    assert cd.security_audit(FIXTURES / "sensitive_sample.pdf").documents


def test_the_guard_is_put_back_exactly_as_it_was_found():
    """The difference between a library and a liability.

    A host application that imported this to scan one file must still be able
    to make its own network calls afterwards.
    """
    original = socket.socket.connect
    assert not offline.is_armed(), "the suite does not run with the guard armed"

    report = cd.security_audit(SAMPLE)

    assert report.run.offline_guard == "armed", "and the audit itself was guarded"
    assert not offline.is_armed()
    assert socket.socket.connect is original
    assert socket.getaddrinfo is not offline._blocked_getaddrinfo


def test_a_path_that_is_not_there_raises_rather_than_returning_nothing():
    """ "No documents found" and "that folder does not exist" are different
    answers, and only one of them is about the documents."""
    with pytest.raises(FileNotFoundError):
        cd.security_audit("no-such-path-exists-here")


def test_the_guard_is_put_back_even_when_the_audit_fails(tmp_path):
    original = socket.socket.connect
    broken = tmp_path / "truncated.pdf"
    broken.write_bytes(b"%PDF-1.7 and nothing else")
    with pytest.raises(Exception):  # noqa: B017 - whatever it raises, the guard restores
        cd.security_audit(broken, config=cd.load_config(tmp_path / "no-config-here"))
    assert not offline.is_armed()
    assert socket.socket.connect is original


def test_a_caller_who_armed_the_guard_keeps_it():
    """Theirs to disarm, not ours. Restoring it would be a surprise."""
    offline.arm()
    try:
        cd.security_audit(SAMPLE)
        assert offline.is_armed(), "we did not take away what we did not install"
    finally:
        offline.disarm()


def test_the_guard_can_be_declined_by_a_caller_who_needs_the_network():
    """Off only on request, and the report records that it was."""
    report = cd.security_audit(SAMPLE, offline_guard=False)
    assert report.run.offline_guard != "armed"
    assert not offline.is_armed()


def test_it_does_not_start_processes_unless_asked():
    """A notebook or a web worker should not get a surprise process pool."""
    report = cd.security_audit(SAMPLE)
    assert report.run.jobs == 1


def test_the_report_can_be_written_out_both_ways(tmp_path):
    import json

    report = cd.full_audit(SAMPLE)
    html = cd.write_html(report, tmp_path / "r.html")
    data = cd.write_json(report, tmp_path / "r.json")
    assert html.exists() and "complydoc" in html.read_text()
    assert json.loads(data.read_text())["run"]["schema_version"] == report.run.schema_version


def test_options_that_do_not_apply_are_ignored_rather_than_rejected():
    """One option set for four functions, so a caller can loop over them."""
    report = cd.security_audit(SAMPLE, monthly_volume=5_000)
    assert report.documents
