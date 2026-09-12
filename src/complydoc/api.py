"""The Python API.

    import complydoc as cd

    report = cd.security_audit("~/contracts")
    for document in report.documents:
        for match in document.sensitive.matches:
            print(document.relative_path, match.label, match.evidence, match.masked)

`extract_text` is the other direction: not what the folder is like, but the
folder's own words with every identifier covered over, chunked, counted in
tokens, and carrying a list of what could not be read.

Readers are pluggable, and the registration hooks are public. `register_extractor`
takes a class satisfying `Extractor` and complydoc will use it like its own;
`register_engine` does the same for OCR, and `register_loader` teaches it a
whole file format nothing here handles yet:

    class MarkdownLoader:
        extensions = (".md",)
        format = cd.DocumentFormat.OTHER

        def load(self, path, options):
            document = cd.Document(path=path, sha256=cd.sha256_of(path), format=self.format)
            page = cd.Page(number=1, width_pt=595.0, height_pt=842.0)
            page.text = path.read_text()
            page.text_source = "native"
            document.pages.append(page)
            return document

    cd.register_loader(MarkdownLoader())

Which is why `Document`, `Page`, `Rect` and the rest of the loader's vocabulary
are exported too: a plug-in point you cannot write against is not one.

Four audit entry points, one per way of asking. `full_audit` runs everything;
the other three run one component each, which is the point of them — asking
only for the identifier scan loads no tokenizer and prices nothing, and is
several times quicker for it.

The three exceptions are exported because a caller has to be able to catch
them by name: `ConfigError` for a configuration that will not load,
`UnknownModelError` for a model nobody ships a price for, and
`NetworkAccessError` if anything in the run reaches for the network. A missing
path raises `FileNotFoundError`, because that is what it is.

Everything named in `complydoc.__all__` is the public surface, and the report
objects it returns are part of it. Anything else in the package is internal and
may be renamed without notice. The shape of a report is versioned:
`report.run.schema_version` moves when it changes, exactly as it does for the
JSON, so code can branch on it.

Two differences from the command line, both deliberate.

The network guard is scoped. The CLI arms it for the life of the process, which
is right when it owns the process; here it is armed for the audit and the socket
module is put back as it was found. A library that permanently broke its host's
network would be indefensible, however good its reasons.

And `jobs` is 1 unless asked otherwise. The CLI reads the folder and decides,
because a person waiting at a terminal wants the cores. A library called from a
notebook, a web worker or another pool should not quietly start processes of its
own.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, Unpack

from complydoc import offline
from complydoc.audit import COMPONENTS, run_audit
from complydoc.config.loader import ConfigError, load_config
from complydoc.cost.estimator import UnknownModelError
from complydoc.extract import Chunk, ExtractionWarning, TextResult, extract_text
from complydoc.ingest.base import (
    Document,
    DocumentFormat,
    IngestOptions,
    Loader,
    LoaderError,
    Page,
    Rect,
    TextBlock,
    sha256_of,
)
from complydoc.ingest.engines.base import Engine, Recognised
from complydoc.ingest.engines.registry import all_engines
from complydoc.ingest.engines.registry import register as register_engine
from complydoc.ingest.extractors.base import Extraction, Extractor, PageSource
from complydoc.ingest.extractors.registry import all_extractors
from complydoc.ingest.extractors.registry import register as register_extractor
from complydoc.ingest.registry import register as register_loader
from complydoc.ingest.registry import supported_extensions
from complydoc.offline import NetworkAccessError
from complydoc.report.html_writer import write_html as _write_html
from complydoc.report.json_writer import write_json as _write_json

if TYPE_CHECKING:
    from complydoc.config.schema import Config
    from complydoc.report.models import AuditReport

__all__ = [
    "AuditOptions",
    "Chunk",
    "ConfigError",
    "Document",
    "DocumentFormat",
    "Engine",
    "Extraction",
    "ExtractionWarning",
    "Extractor",
    "IngestOptions",
    "Loader",
    "LoaderError",
    "NetworkAccessError",
    "Page",
    "PageSource",
    "Recognised",
    "Rect",
    "TextBlock",
    "TextResult",
    "UnknownModelError",
    "all_engines",
    "all_extractors",
    "cost_audit",
    "extract_text",
    "full_audit",
    "load_config",
    "readiness_audit",
    "register_engine",
    "register_extractor",
    "register_loader",
    "security_audit",
    "sha256_of",
    "supported_extensions",
    "write_html",
    "write_json",
]


class AuditOptions(TypedDict, total=False):
    """Everything the four entry points accept beyond the folder itself.

    One set for all of them, and an option that means nothing to the components
    being run is ignored rather than rejected — `monthly_volume` on a scan for
    identifiers has nothing to extrapolate, and refusing it would only make the
    functions harder to call from a loop.
    """

    config: Config | None
    """A loaded configuration. `load_config()` is used when this is absent."""
    ocr: bool
    """Read pages with no text layer. Slower, and finds what a scan is hiding."""
    reveal: bool
    """Put identifiers in the report in full. Off, and the report says which it was."""
    recurse: bool
    password: str
    monthly_volume: int | None
    models: Sequence[str] | None
    """Price against these models instead of the configured comparison."""
    extractor: str | None
    compare_extractors: Sequence[str]
    compare_engines: Sequence[str]
    sample: int | None
    """Audit this many documents, keeping each file type's share of the folder."""
    jobs: int
    """Worker processes. 1 by default; 0 reads the folder and decides."""
    page_images: bool
    extracted_text: bool
    """Keep the text read off each page. It is the document, so it is off by default."""
    offline_guard: bool
    """Block outbound sockets for the duration. On, and only off for a caller
    who knows their process needs the network while this runs."""
    progress: Callable[[int, int, Path], None] | None
    """Called with (finished, total, path) as each document completes."""


def _audit(
    target: str | os.PathLike[str],
    components: Sequence[str],
    options: AuditOptions,
) -> AuditReport:
    """The one implementation. The four public names differ only in components."""
    folder = Path(target).expanduser()
    # A command can print an error and exit; a library has to raise. Returning
    # an empty report for a path that is not there would read as "nothing was
    # found in these documents", which is a different and much worse answer.
    if not folder.exists():
        raise FileNotFoundError(f"no such file or folder: {folder}")
    config = options.get("config") or load_config()
    with offline.guarded(options.get("offline_guard", True)):
        return run_audit(
            folder,
            config,
            components,
            ocr=options.get("ocr", False),
            reveal=options.get("reveal", False),
            monthly_volume=options.get("monthly_volume"),
            select_models=options.get("models"),
            recurse=options.get("recurse", True),
            page_images=options.get("page_images", False),
            extracted_text=options.get("extracted_text", False),
            password=options.get("password", ""),
            extractor=options.get("extractor"),
            compare_extractors=tuple(options.get("compare_extractors") or ()),
            compare_engines=tuple(options.get("compare_engines") or ()),
            jobs=options.get("jobs", 1),
            sample=options.get("sample"),
            progress=options.get("progress"),
        )


def full_audit(target: str | os.PathLike[str], **options: Unpack[AuditOptions]) -> AuditReport:
    """Audit a file or folder on every component.

    Cost, readiness and the identifier scan, with the global readiness score
    and the quick wins that follow from all three.
    """
    return _audit(target, COMPONENTS, options)


def security_audit(target: str | os.PathLike[str], **options: Unpack[AuditOptions]) -> AuditReport:
    """Find personal and financial identifiers, and nothing else.

    Values arrive masked. `report.documents[i].sensitive.matches` carries each
    one with its `severity` and its `evidence` tier — `confirmed` where a
    checksum passed, down to `model` for a statistical guess.
    """
    return _audit(target, ("sensitive",), options)


def cost_audit(target: str | os.PathLike[str], **options: Unpack[AuditOptions]) -> AuditReport:
    """Estimate what these documents would cost an LLM to read.

    Per model and per architecture — the text layer, the text layer with OCR
    behind it, and every page sent as an image.
    """
    return _audit(target, ("cost",), options)


def readiness_audit(target: str | os.PathLike[str], **options: Unpack[AuditOptions]) -> AuditReport:
    """Measure how ready these documents are to extract data from.

    The signals are the product; `report.documents[i].readiness.signals` is the
    table, and a signal that could not be measured says so rather than
    reporting a zero.
    """
    return _audit(target, ("readiness",), options)


def write_html(
    report: AuditReport,
    path: str | os.PathLike[str],
    *,
    config: Config | None = None,
) -> Path:
    """Write the report as one self-contained HTML file, and return where.

    Pass the same `config` the audit used if it was not the default one: the
    page echoes parts of it, so a report written against a different
    configuration would describe settings that did not produce it.
    """
    return _write_html(report, config or load_config(), Path(path).expanduser())


def write_json(report: AuditReport, path: str | os.PathLike[str]) -> Path:
    """Write the report as JSON, and return where. Same shape the CLI writes."""
    return _write_json(report, Path(path).expanduser())
