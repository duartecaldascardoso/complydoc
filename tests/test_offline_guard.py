"""The offline promise, enforced rather than asserted in a README."""

from __future__ import annotations

import socket

import pytest

from complydoc import offline
from complydoc.audit import run_audit
from tests.helpers import FIXTURES


@pytest.fixture
def armed():
    offline.arm()
    yield
    offline.disarm()


def test_connect_is_blocked(armed):
    with pytest.raises(offline.NetworkAccessError):
        socket.create_connection(("example.com", 80))


def test_dns_lookup_is_blocked(armed):
    with pytest.raises(offline.NetworkAccessError):
        socket.getaddrinfo("example.com", 80)


def test_socket_connect_is_blocked(armed):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(offline.NetworkAccessError):
            sock.connect(("93.184.216.34", 80))
    finally:
        sock.close()


def test_guard_status_reports_armed(armed):
    assert offline.guard_status() == "armed"


def test_a_full_audit_completes_with_the_guard_armed(armed, config):
    """The load-bearing test: everything works with the network cut off."""
    report = run_audit(FIXTURES, config)
    assert report.run.offline_guard == "armed"
    assert report.aggregate is not None
    assert report.aggregate.documents_audited > 0
    # Token counting in particular must not have silently fallen back.
    fidelities = {
        model.text_token_fidelity
        for document in report.documents
        if document.cost
        for model in document.cost.models
    }
    assert "estimated" not in fidelities, (
        "a tokenizer vocabulary was unavailable offline; it should be vendored"
    )
