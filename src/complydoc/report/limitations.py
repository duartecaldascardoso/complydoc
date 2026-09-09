"""Generate the limitations section from what actually happened during the run.

This is deliberately not a fixed list of caveats. It is assembled from the run's
own facts — which pages could not be read, which detectors were unavailable,
which signals did not apply, which prices are unverified — so it describes this
run rather than describing the tool in general.

If a section here is empty, that is itself information: nothing was skipped.
"""

from __future__ import annotations

from collections import defaultdict

from complydoc.config.loader import StalenessWarning
from complydoc.config.schema import Config
from complydoc.ingest.base import SkipRecord
from complydoc.readiness.base import SignalStatus
from complydoc.report.models import DocumentReport, Limitation, RunMetadata
from complydoc.text import count, plural

__all__ = ["build_limitations"]


def build_limitations(
    run: RunMetadata,
    documents: list[DocumentReport],
    skipped: list[SkipRecord],
    staleness: list[StalenessWarning],
    config: Config,
) -> list[Limitation]:
    limitations: list[Limitation] = []

    # --- Only part of the folder was looked at ----------------------------
    if run.sampled_from is not None:
        limitations.append(
            Limitation(
                area="Sampling",
                statement=(
                    f"--sample limited this run to {run.sample_size} of the {run.sampled_from} "
                    f"documents found. Every total and monthly figure describes that sample, not "
                    f"the folder. The sample keeps each file type's share of the folder and is "
                    f"chosen the same way every time, so two runs of this folder compare."
                ),
                severity="important",
            )
        )

    # --- Prices nobody checked --------------------------------------------
    priced = next((d.cost.models for d in documents if d.cost), [])
    imported = sorted({m.display_name for m in priced if m.price_source == "imported"})
    if imported:
        taken = next((m.imported_on for m in priced if m.imported_on), None)
        limitations.append(
            Limitation(
                area="Price provenance",
                statement=(
                    f"{count(len(imported), 'model')} "
                    f"{'is' if len(imported) == 1 else 'are'} priced from a maintained "
                    f"third-party table{f' taken on {taken.isoformat()}' if taken else ''} rather "
                    f"than from the provider's own page. Nobody has checked "
                    f"{'that number' if len(imported) == 1 else 'those numbers'} against the "
                    f"provider, and a price that has moved since is a figure that moved with it."
                ),
                affected=imported,
                severity="important",
            )
        )

    # --- Files that were never opened -------------------------------------
    if skipped:
        by_reason: dict[str, list[str]] = defaultdict(list)
        for record in skipped:
            by_reason[record.reason].append(record.path.name)
        for reason, files in sorted(by_reason.items()):
            limitations.append(
                Limitation(
                    area="Files not examined",
                    statement=(
                        f"{count(len(files), 'file')} were not examined because they could not be "
                        f"opened ({reason}). Nothing in this report says anything about them."
                    ),
                    affected=sorted(files),
                    severity="important",
                )
            )

    # --- Pages with no readable text --------------------------------------
    unreadable: dict[str, list[int]] = {}
    for document in documents:
        if document.sensitive and document.sensitive.unreadable_pages:
            unreadable[document.relative_path] = document.sensitive.unreadable_pages
    if unreadable:
        total = sum(len(v) for v in unreadable.values())
        if run.ocr_requested and not run.ocr_available:
            why = "OCR was requested but the optional OCR extra is not installed"
        elif not run.ocr_requested:
            why = "OCR was not requested (pass --ocr to read scanned pages)"
        else:
            why = "OCR ran but recognised no text on them"
        limitations.append(
            Limitation(
                area="Pages that could not be read",
                statement=(
                    f"{count(total, 'page')} carried no readable text because {why}. Those pages "
                    f"were not searched for sensitive information, so a count of zero for "
                    f"them means 'not looked at', not 'nothing there'."
                ),
                affected=[
                    f"{path}: {plural(len(pages), 'page')} {', '.join(map(str, pages))}"
                    for path, pages in sorted(unreadable.items())
                ],
                severity="important",
            )
        )

    # --- Encrypted documents ----------------------------------------------
    encrypted = [
        d.relative_path
        for d in documents
        if any("password protected" in w for w in d.load_warnings)
    ]
    if encrypted:
        limitations.append(
            Limitation(
                area="Encrypted documents",
                statement=(
                    f"{count(len(encrypted), 'document')} are password protected and could not be "
                    f"opened, so nothing was measured for them beyond the fact of encryption."
                ),
                affected=sorted(encrypted),
                severity="important",
            )
        )

    # --- Detector categories that never ran -------------------------------
    unscanned: dict[str, tuple[str, list[str]]] = {}
    for document in documents:
        if not document.sensitive:
            continue
        for entry in document.sensitive.unscanned_categories:
            label, affected = unscanned.setdefault(entry.category, (entry.reason, []))
            affected.append(document.relative_path)
    for category, (reason, affected) in sorted(unscanned.items()):
        label = (
            config.sensitive.categories[category].label
            if category in config.sensitive.categories
            else category
        )
        limitations.append(
            Limitation(
                area="Categories not scanned",
                statement=(
                    f"{label} was not scanned for at all, because {reason}. No conclusion "
                    f"about this category can be drawn from this report."
                ),
                affected=sorted(set(affected)),
                severity="important",
            )
        )

    # --- Signals that did not apply ---------------------------------------
    # Keyed by (signal, reason). Grouping on the signal alone would attach one
    # document's reason to every other document in the group, which produced
    # entries telling the reader a PNG was skipped because "this is a docx file".
    na_signals: dict[tuple[str, str], list[str]] = {}
    error_signals: dict[tuple[str, str], list[str]] = {}
    for document in documents:
        if not document.readiness:
            continue
        for signal in document.readiness.signals:
            if signal.status is SignalStatus.NOT_APPLICABLE:
                bucket = na_signals
            elif signal.status is SignalStatus.ERROR:
                bucket = error_signals
            else:
                continue
            key = (signal.name, signal.reason or "no reason recorded")
            bucket.setdefault(key, []).append(document.relative_path)

    # Signals that simply do not apply to a format are a property of the document,
    # not of the run. They are listed on the document itself; repeating nineteen of
    # them here buried everything that actually needed attention.
    _ = na_signals

    for (name, reason), affected in sorted(error_signals.items()):
        limitations.append(
            Limitation(
                area="Signals that failed",
                statement=(
                    f'"{name}" raised an error on {count(len(set(affected)), "document")} and was '
                    f"skipped: {reason}. This is a defect in complydoc, not a property of "
                    f"the document."
                ),
                affected=sorted(set(affected)),
                severity="important",
            )
        )

    # --- What alignment-detected tables cannot report ---------------------
    aligned = [
        d.relative_path
        for d in documents
        if d.readiness
        and any(
            s.id == "table_count"
            and s.status is SignalStatus.MEASURED
            and s.detail.get("aligned_tables")
            for s in d.readiness.signals
        )
    ]
    if aligned:
        limitations.append(
            Limitation(
                area="Table detection",
                statement=(
                    f"{count(len(aligned), 'document')} contain tables held together by "
                    f"whitespace rather than ruling lines. They are counted, but a table "
                    f"with no rules carries nothing to read a span from, so header depth "
                    f"and merged cells are not measured for them."
                ),
                affected=sorted(aligned),
            )
        )

    # --- Documents with no fixed pagination -------------------------------
    unpaged = [d.relative_path for d in documents if not d.page_count_known]
    if unpaged:
        limitations.append(
            Limitation(
                area="Page counts",
                statement=(
                    f"{count(len(unpaged), 'document')} have no fixed pagination until they are "
                    f"rendered, so their page count, page dimensions and any per-page cost "
                    f"figure are not measurements. Vision-path costs are reported as not "
                    f"applicable for them rather than as zero."
                ),
                affected=sorted(unpaged),
            )
        )

    # --- Pricing provenance ------------------------------------------------
    for warning in staleness:
        limitations.append(
            Limitation(
                area="Price provenance",
                statement=warning.message,
                severity="important",
            )
        )

    disabled = [m.id for m in config.pricing.models if not m.enabled]
    if disabled:
        limitations.append(
            Limitation(
                area="Models not costed",
                statement=(
                    f"{len(disabled)} model entr(y/ies) in pricing.yaml carry no price and "
                    f"are switched off, so no cost was computed for them. complydoc does not "
                    f"invent prices; fill them in and set last_verified to include them."
                ),
                affected=sorted(disabled),
            )
        )

    # --- Token counting fidelity -------------------------------------------
    fidelities: dict[str, list[str]] = defaultdict(list)
    for document in documents:
        if not document.cost:
            continue
        for model in document.cost.models:
            if model.text_token_fidelity != "exact" and model.text_token_note:
                fidelities[model.text_token_note].append(model.display_name)
    for note, models in fidelities.items():
        limitations.append(
            Limitation(
                area="Token counting",
                statement=note,
                affected=sorted(set(models)),
            )
        )

    # --- Output tokens are not estimated -----------------------------------
    if run.components_run and "cost" in run.components_run:
        limitations.append(
            Limitation(
                area="Cost scope",
                statement=(
                    "Only input cost is estimated. What you pay for output depends entirely "
                    "on what you ask the model to produce, which this tool cannot know, so "
                    "it is left out rather than guessed at. Your real bill will be higher."
                ),
            )
        )
        if config.pricing.currency.report_in.upper() == "USD":
            limitations.append(
                Limitation(
                    area="Currency",
                    statement=(
                        "Costs are shown in US dollars, the currency the providers publish "
                        "in. No verified exchange rate is configured, so no conversion to "
                        "sterling was applied."
                    ),
                )
            )

    # --- Extrapolation ------------------------------------------------------
    if run.monthly_volume:
        limitations.append(
            Limitation(
                area="Volume extrapolation",
                statement=(
                    f"Monthly and annual figures assume the {count(len(documents), 'document')} "
                    f"audited here are representative of the {run.monthly_volume:,} you "
                    f"process each month. If this sample is unusual, so is the projection."
                ),
                severity="important",
            )
        )

    # --- Reveal --------------------------------------------------------------
    if run.reveal_used:
        limitations.append(
            Limitation(
                area="Masking",
                statement=(
                    "This report was generated with --reveal, so it contains unmasked "
                    "sensitive values. Treat this file with the same care as the documents "
                    "it describes."
                ),
                severity="important",
            )
        )

    # --- Signals registered but not configured -------------------------------
    unconfigured: set[str] = set()
    for document in documents:
        if document.readiness:
            unconfigured |= set(document.readiness.unconfigured_signals)
    if unconfigured:
        limitations.append(
            Limitation(
                area="Configuration",
                statement=(
                    "These signals are registered in code but have no entry in "
                    "readiness.yaml, so they were measured without a rating or a weight."
                ),
                affected=sorted(unconfigured),
            )
        )

    # --- Components that were not run at all ---------------------------------
    all_components = {"cost", "readiness", "sensitive"}
    not_run = sorted(all_components - set(run.components_run))
    if not_run:
        limitations.append(
            Limitation(
                area="Components not run",
                statement=(
                    f"This run covered only {', '.join(sorted(run.components_run))}. "
                    f"Nothing here says anything about {', '.join(not_run)}."
                ),
                severity="important",
            )
        )

    return limitations
