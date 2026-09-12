"""complydoc — an offline pre-purchase diagnostic for document automation.

Point it at a folder of business documents and it answers three questions: what
they would cost to process with an LLM, how ready they are to extract data
from, and what personal or financial information they hold.

    import complydoc as cd

    report = cd.security_audit("~/contracts")
    print(report.aggregate.sensitive_total, "identifiers found")

    report = cd.full_audit("~/contracts", ocr=True)
    print(report.overall.score, report.overall.label)
    for win in report.quick_wins:
        print(win.actor, win.title, len(win.documents))

    cd.write_html(report, "audit.html")

The names below are the public API, and the report objects they return are part
of it. Everything else in this package is internal: it may be renamed or
removed without notice, so treat an import from `complydoc.something` as a
private call and expect it to break.

A report's shape is versioned. `report.run.schema_version` moves when it
changes — the same number the JSON carries — so code that reads one can branch
on it rather than guess.

Nothing here reaches the network. The guard is armed for the duration of each
audit and the socket module is restored afterwards, so an audit cannot leak a
document and cannot break a host application that needs the network of its own.
"""

from __future__ import annotations

# Before the import below, which reaches code that reads it back off this module.
__version__ = "0.3.0"

from complydoc import api as _api
from complydoc.api import *  # noqa: F403

__all__ = ["__version__", *_api.__all__]
"""The public surface: everything `complydoc.api` exports, plus the version.

One list rather than two, because two would drift and a name that appears here
by accident is a name we cannot take back."""
