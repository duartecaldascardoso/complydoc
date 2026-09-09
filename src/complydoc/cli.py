"""Command line interface.

Four commands. `audit` runs everything; `cost`, `readiness` and `sensitive` run
one component each, so someone who only wants the sensitive data scan can have
exactly that and nothing else.

The network guard is armed before any document is opened, on every path.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from complydoc import __version__, offline
from complydoc.audit import COMPONENTS, run_audit
from complydoc.config.loader import ConfigError, load_config
from complydoc.cost.estimator import UnknownModelError
from complydoc.report.html_writer import write_html
from complydoc.report.json_writer import write_json
from complydoc.report.models import AuditReport
from complydoc.text import count

app = typer.Typer(
    add_completion=False,
    no_args_is_help=False,
    help=(
        "Audit a folder of business documents offline: what they would cost to process "
        "with an LLM, how hard they are to extract from, and what sensitive information "
        "they contain. No document content ever leaves this machine."
    ),
)
console = Console()
errors = Console(stderr=True)


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Run `complydoc` on its own to audit the folder you are standing in.

    Anything more specific is a subcommand: `complydoc audit <path>`, `cost`,
    `readiness`, `sensitive`, `models`, `schema`, `doctor`.
    """
    if ctx.invoked_subcommand is not None:
        return
    here = Path.cwd()
    console.print(f"[dim]Auditing[/] {here}")
    _run(
        here,
        COMPONENTS,
        DEFAULT_OUT,
        "complydoc",
        None,
        True,
        True,
        False,
    )


TargetArg = Annotated[Path, typer.Argument(help="A file or folder to audit.")]
OutDirOpt = Annotated[
    Path,
    typer.Option("--out", "-o", help="Directory for the reports."),
]
DEFAULT_OUT = Path(".complydoc")
"""Hidden, so a second run does not discover the first run's own reports."""
ConfigOpt = Annotated[
    Path | None, typer.Option("--config-dir", help="Override the config directory.")
]
OcrOpt = Annotated[
    bool,
    typer.Option(
        "--ocr/--no-ocr",
        help="Read scanned pages with local OCR. On by default, so a scanned page is "
        "still readable; --no-ocr is faster.",
    ),
]
RecurseOpt = Annotated[
    bool, typer.Option("--recurse/--no-recurse", help="Descend into subfolders.")
]
NameOpt = Annotated[str, typer.Option("--name", help="Base filename for the reports.")]
PageImagesOpt = Annotated[
    bool,
    typer.Option(
        "--page-images/--no-page-images",
        help="Embed a picture of each page beside what was extracted from it. "
        "On by default; --no-page-images leaves the pictures out and makes the "
        "report considerably smaller.",
    ),
]
ExtractedTextOpt = Annotated[
    bool,
    typer.Option(
        "--extracted-text/--no-extracted-text",
        help="Include the text read off each page, so it can be read beside the "
        "page it came from. On by default; --no-extracted-text leaves the report "
        "carrying no document content.",
    ),
]
OcrCompareOpt = Annotated[
    bool,
    typer.Option(
        "--ocr-compare",
        help="Also OCR pages that already have a text layer, so the text layer and "
        "what OCR reads can be compared. Implies --extracted-text.",
    ),
]
ExtractorOpt = Annotated[
    str | None,
    typer.Option(
        "--extractor",
        help="Which library reads the text layer. Defaults to pdfplumber, the "
        "richest; pdfium is far quicker and reads no table structure. "
        "See: complydoc extractors.",
    ),
]
CompareExtractorsOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--compare-extractor",
        help="Also read every page with this one and report where the two "
        "disagree, repeatable. It never changes a finding.",
    ),
]
OcrEngineOpt = Annotated[
    str | None,
    typer.Option("--ocr-engine", help="Which local OCR engine to read scans with."),
]
SaveTextOpt = Annotated[
    Path | None,
    typer.Option(
        "--save-text",
        help="Also write the text read off each document into this folder, one file "
        "per document. Reading a scanned folder is the slow part; this keeps the "
        "result so nothing has to OCR it again.",
    ),
]
PrintJsonOpt = Annotated[
    bool,
    typer.Option(
        "--print-json",
        help="Write the JSON report to stdout and nothing else, for piping into "
        "another tool or an agent. Progress goes to stderr.",
    ),
]
QuietOpt = Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress output.")]
JobsOpt = Annotated[
    int,
    typer.Option(
        "--jobs",
        "-j",
        help="Documents to process at once. The default reads the size of the "
        "folder and decides; 1 forces one process. Changes how long the run "
        "takes and nothing about what it finds.",
    ),
]
SampleOpt = Annotated[
    int | None,
    typer.Option(
        "--sample",
        help="Audit at most this many documents, keeping each file type's share of "
        "the folder. The report says it is a sample.",
    ),
]
PasswordOpt = Annotated[
    str,
    typer.Option(
        "--password",
        help="Password to try on encrypted PDFs. Passed on the command line, so it "
        "will be in your shell history.",
    ),
]
ModelOpt = Annotated[
    list[str] | None,
    typer.Option(
        "--model",
        "-m",
        help="Model id to price, repeatable. Defaults to every priced model. "
        "See: complydoc models.",
    ),
]


def _load(config_dir: Path | None) -> object:
    try:
        return load_config(config_dir)
    except ConfigError as exc:
        errors.print(f"[bold red]Configuration error[/]\n{exc}")
        raise typer.Exit(code=2) from exc


def _emit(
    report: AuditReport,
    config: object,
    out: Path,
    name: str,
    quiet: bool,
    save_text: Path | None = None,
    extractor: str | None = None,
    compare_extractors: list[str] | None = None,
    ocr_engine: str | None = None,
) -> None:
    json_path = write_json(report, out / f"{name}.json").resolve()
    html_path = write_html(report, config, out / f"{name}.html").resolve()  # type: ignore[arg-type]

    written: list[Path] = []
    if save_text is not None:
        from complydoc.report.text_writer import write_text

        written = write_text(report, save_text)

    if quiet:
        return
    # file:// URLs, so terminals that support hyperlinks open these on a click.
    console.print()
    console.print(
        f"[bold]Report[/]  [link=file://{html_path}]{html_path}[/link]", no_wrap=True, crop=False
    )
    console.print(
        f"[bold]Data[/]    [link=file://{json_path}]{json_path}[/link]", no_wrap=True, crop=False
    )
    if save_text is not None:
        folder = save_text.expanduser().resolve()
        console.print(
            f"[bold]Text[/]    [link=file://{folder}]{folder}[/link]  "
            f"[dim]{count(len(written), 'file')} — these are the documents, "
            f"identifiers and all[/]",
            no_wrap=True,
            crop=False,
        )


def _summary(report: AuditReport) -> None:
    aggregate = report.aggregate
    if aggregate is None:
        return

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Documents", f"{aggregate.documents_audited} ({aggregate.pages_total} pages)")
    if aggregate.documents_skipped:
        table.add_row("Skipped", f"[yellow]{aggregate.documents_skipped}[/]")
    if aggregate.total_text_path_usd is not None:
        table.add_row("Text path", f"${aggregate.total_text_path_usd:,.4f}")
    if aggregate.total_vision_path_usd is not None:
        table.add_row("Vision path", f"${aggregate.total_vision_path_usd:,.4f}")
    if aggregate.annual_text_usd is not None:
        table.add_row("Annual (text)", f"${aggregate.annual_text_usd:,.2f}")
    if aggregate.annual_vision_usd is not None:
        table.add_row("Annual (vision)", f"${aggregate.annual_vision_usd:,.2f}")
    if aggregate.mean_readiness_score is not None:
        table.add_row("Mean readiness", f"{aggregate.mean_readiness_score}/100")
    if "sensitive" in report.run.components_run:
        table.add_row(
            "Sensitive items",
            f"{aggregate.sensitive_total} in "
            f"{aggregate.documents_with_sensitive_data}/{aggregate.documents_audited} docs",
        )
    if aggregate.pages_unreadable:
        table.add_row("Unread pages", f"[yellow]{aggregate.pages_unreadable}[/]")
    console.print(table)

    important = [x for x in report.limitations if x.severity == "important"]
    if important:
        console.print(
            f"\n[yellow]{count(len(important), 'important limitation')}[/] — see the report before "
            f"drawing conclusions."
        )
    for warning in report.staleness_warnings:
        console.print(f"[yellow]Price provenance:[/] {warning}")


def _run(
    target: Path,
    components: tuple[str, ...],
    out: Path,
    name: str,
    config_dir: Path | None,
    ocr: bool,
    recurse: bool,
    quiet: bool,
    reveal: bool = False,
    monthly_volume: int | None = None,
    resolution: str = "medium",
    select_models: list[str] | None = None,
    page_images: bool = True,
    extracted_text: bool = True,
    ocr_compare: bool = False,
    print_json: bool = False,
    password: str = "",
    jobs: int = 0,
    sample: int | None = None,
    save_text: Path | None = None,
    extractor: str | None = None,
    compare_extractors: list[str] | None = None,
    ocr_engine: str | None = None,
) -> None:
    offline.arm()
    if ocr_engine:
        from complydoc.ingest import ocr as ocr_module

        ocr_module.select(ocr_engine)
    # stdout has to stay pure JSON when a caller is parsing it.
    global console
    if print_json:
        console = errors
        quiet = True
    config = _load(config_dir)

    if not target.exists():
        errors.print(f"[bold red]No such path:[/] {target}")
        raise typer.Exit(code=2)

    if reveal:
        errors.print(
            "[bold yellow]--reveal is set.[/] The reports will contain unmasked sensitive "
            "values. Treat them as sensitive documents in their own right."
        )

    def progress(index: int, total: int, path: Path) -> None:
        if not quiet:
            console.print(f"[dim]({index}/{total})[/] {path.name}")

    try:
        report = run_audit(
            target,
            config,  # type: ignore[arg-type]
            components,
            ocr=ocr,
            reveal=reveal,
            monthly_volume=monthly_volume,
            resolution=resolution,
            select_models=select_models,
            page_images=page_images,
            extracted_text=extracted_text or ocr_compare,
            ocr_compare=ocr_compare,
            recurse=recurse,
            password=password,
            extractor=extractor,
            compare_extractors=tuple(compare_extractors or ()),
            jobs=jobs,
            sample=sample,
            progress=progress if not quiet else None,
        )
    except UnknownModelError as exc:
        errors.print(f"[bold red]Unknown model[/] — {exc}\n\nRun 'complydoc models' to list them.")
        raise typer.Exit(code=2) from exc
    if not quiet:
        _summary(report)
    _emit(report, config, out, name, quiet, save_text)
    if print_json:
        import json as _json

        from complydoc.report.json_writer import to_dict

        sys.stdout.write(
            _json.dumps(to_dict(report), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        )


@app.command()
def audit(
    target: TargetArg,
    out: OutDirOpt = DEFAULT_OUT,
    name: NameOpt = "complydoc",
    monthly_volume: Annotated[
        int | None,
        typer.Option("--monthly-volume", help="Documents per month, to extrapolate cost."),
    ] = None,
    resolution: Annotated[
        str, typer.Option("--vision-resolution", help="Headline vision resolution preset.")
    ] = "medium",
    reveal: Annotated[
        bool,
        typer.Option(
            "--reveal",
            help="Print sensitive values in full. Off by default, and the report says so.",
        ),
    ] = False,
    model: ModelOpt = None,
    page_images: PageImagesOpt = True,
    extracted_text: ExtractedTextOpt = True,
    ocr_compare: OcrCompareOpt = False,
    password: PasswordOpt = "",
    jobs: JobsOpt = 0,
    sample: SampleOpt = None,
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = True,
    recurse: RecurseOpt = True,
    extractor: ExtractorOpt = None,
    ocr_engine: OcrEngineOpt = None,
    compare_extractor: CompareExtractorsOpt = None,
    save_text: SaveTextOpt = None,
    print_json: PrintJsonOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Run all three components and write both reports."""
    _run(
        target,
        COMPONENTS,
        out,
        name,
        config_dir,
        ocr,
        recurse,
        quiet,
        reveal=reveal,
        monthly_volume=monthly_volume,
        resolution=resolution,
        select_models=model,
        page_images=page_images,
        extracted_text=extracted_text,
        ocr_compare=ocr_compare,
        print_json=print_json,
        save_text=save_text,
        extractor=extractor,
        compare_extractors=compare_extractor,
        ocr_engine=ocr_engine,
        password=password,
        jobs=jobs,
        sample=sample,
    )


@app.command()
def cost(
    target: TargetArg,
    out: OutDirOpt = DEFAULT_OUT,
    name: NameOpt = "complydoc-cost",
    monthly_volume: Annotated[
        int | None,
        typer.Option("--monthly-volume", help="Documents per month, to extrapolate cost."),
    ] = None,
    resolution: Annotated[
        str, typer.Option("--vision-resolution", help="Headline vision resolution preset.")
    ] = "medium",
    model: ModelOpt = None,
    password: PasswordOpt = "",
    jobs: JobsOpt = 0,
    sample: SampleOpt = None,
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = True,
    recurse: RecurseOpt = True,
    extractor: ExtractorOpt = None,
    ocr_engine: OcrEngineOpt = None,
    compare_extractor: CompareExtractorsOpt = None,
    save_text: SaveTextOpt = None,
    print_json: PrintJsonOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Estimate LLM processing cost only."""
    _run(
        target,
        ("cost",),
        out,
        name,
        config_dir,
        ocr,
        recurse,
        quiet,
        monthly_volume=monthly_volume,
        resolution=resolution,
        select_models=model,
        print_json=print_json,
        save_text=save_text,
        extractor=extractor,
        compare_extractors=compare_extractor,
        ocr_engine=ocr_engine,
        password=password,
        jobs=jobs,
        sample=sample,
    )


@app.command()
def readiness(
    target: TargetArg,
    out: OutDirOpt = DEFAULT_OUT,
    name: NameOpt = "complydoc-readiness",
    extracted_text: ExtractedTextOpt = True,
    ocr_compare: OcrCompareOpt = False,
    password: PasswordOpt = "",
    jobs: JobsOpt = 0,
    sample: SampleOpt = None,
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = True,
    recurse: RecurseOpt = True,
    extractor: ExtractorOpt = None,
    ocr_engine: OcrEngineOpt = None,
    compare_extractor: CompareExtractorsOpt = None,
    save_text: SaveTextOpt = None,
    print_json: PrintJsonOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Measure extraction readiness signals only."""
    _run(
        target,
        ("readiness",),
        out,
        name,
        config_dir,
        ocr,
        recurse,
        quiet,
        extracted_text=extracted_text,
        ocr_compare=ocr_compare,
        print_json=print_json,
        save_text=save_text,
        extractor=extractor,
        compare_extractors=compare_extractor,
        ocr_engine=ocr_engine,
        password=password,
        jobs=jobs,
        sample=sample,
    )


@app.command()
def sensitive(
    target: TargetArg,
    out: OutDirOpt = DEFAULT_OUT,
    name: NameOpt = "complydoc-sensitive",
    reveal: Annotated[
        bool,
        typer.Option(
            "--reveal",
            help="Print sensitive values in full. Off by default, and the report says so.",
        ),
    ] = False,
    page_images: PageImagesOpt = True,
    extracted_text: ExtractedTextOpt = True,
    password: PasswordOpt = "",
    jobs: JobsOpt = 0,
    sample: SampleOpt = None,
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = True,
    recurse: RecurseOpt = True,
    extractor: ExtractorOpt = None,
    ocr_engine: OcrEngineOpt = None,
    compare_extractor: CompareExtractorsOpt = None,
    save_text: SaveTextOpt = None,
    print_json: PrintJsonOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Scan for personal and financial identifiers only."""
    _run(
        target,
        ("sensitive",),
        out,
        name,
        config_dir,
        ocr,
        recurse,
        quiet,
        reveal=reveal,
        page_images=page_images,
        extracted_text=extracted_text,
        print_json=print_json,
        save_text=save_text,
        extractor=extractor,
        compare_extractors=compare_extractor,
        ocr_engine=ocr_engine,
        password=password,
        jobs=jobs,
        sample=sample,
    )


@app.command()
def skill(
    install: Annotated[
        bool,
        typer.Option("--install", help="Copy the skill into ~/.claude/skills/complydoc."),
    ] = False,
    target: Annotated[
        Path | None, typer.Option("--to", help="Install somewhere other than ~/.claude/skills.")
    ] = None,
) -> None:
    """Print the agent skill, or install it so an agent picks complydoc up on its own."""
    import shutil
    from importlib.resources import files

    source = files("complydoc.skill").joinpath("SKILL.md")
    if not install:
        console.print(source.read_text(encoding="utf-8"))
        console.print("\n[dim]Install it with:  complydoc skill --install[/]", highlight=False)
        return

    root = (target or Path.home() / ".claude" / "skills") / "complydoc"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "SKILL.md"
    with source.open("rb") as handle, destination.open("wb") as out:
        shutil.copyfileobj(handle, out)
    console.print(f"Installed  [link=file://{destination}]{destination}[/link]", no_wrap=True)
    console.print("[dim]Start a new agent session for it to be picked up.[/]")


@app.command()
def schema() -> None:
    """Print the JSON schema of the report, for a caller that needs to parse it."""
    import json

    from complydoc.report.models import SCHEMA_VERSION

    console.print(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "top_level_keys": [
                    "run",
                    "documents",
                    "skipped",
                    "cost",
                    "aggregate",
                    "limitations",
                    "staleness_warnings",
                    "signal_weights",
                    "config_masking",
                ],
                "run": {
                    "components_run": "list of cost | readiness | sensitive",
                    "offline_guard": "armed | not_armed",
                    "reveal_used": "bool — true means values are NOT masked",
                    "page_images_used": "bool",
                    "extracted_text_used": "bool",
                    "config_digest": "identifies the config that produced these numbers",
                },
                "documents[]": {
                    "relative_path": "str",
                    "sha256": "str",
                    "format": "pdf | image | docx | xlsx",
                    "cost.models[]": "per-model text and vision token counts and USD",
                    "readiness.signals[]": "id, value, rating, weight, why, status",
                    "readiness.score": "value 0-100, higher is better; label; low_confidence",
                    "sensitive.matches[]": "category, page, line, column, masked, severity",
                    "sensitive.unreadable_pages": "pages that were not searched at all",
                },
                "aggregate": "folder totals: cost, signal_distribution, sensitive_by_category",
                "limitations[]": "area, statement, affected[], severity (info | important)",
            },
            indent=2,
        )
    )


@app.command()
def doctor(config_dir: ConfigOpt = None) -> None:
    """Report what is installed, what is not, and what that costs you."""
    offline.arm()
    from complydoc.cost.tokenizer import available_encodings
    from complydoc.ingest import ocr as ocr_module
    from complydoc.ingest.registry import supported_extensions

    config = _load(config_dir)
    console.print(f"[bold]complydoc {__version__}[/] · Python {sys.version.split()[0]}")
    console.print(f"Network guard: [green]{offline.guard_status()}[/]")
    console.print(f"Config: {config.source_dir} (digest {config.digest})")  # type: ignore[attr-defined]
    console.print(f"Formats: {', '.join(supported_extensions())}")
    console.print(f"Tokenizer vocabularies vendored: {len(available_encodings())}")

    if ocr_module.available():
        console.print(f"OCR: [green]available[/] ({ocr_module.engine_name()})")
    else:
        console.print(f"OCR: [yellow]unavailable[/] — {ocr_module.unavailable_reason()}")

    from complydoc.sensitive.detectors.ner import model_available

    checked = False
    for category in config.sensitive.enabled_categories.values():  # type: ignore[attr-defined]
        if category.detector == "ner" and category.model is not None and not checked:
            checked = True
            ok, reason = model_available(category.model.name)
            if ok:
                console.print(f"Name detection: [green]available[/] ({category.model.name})")
            else:
                console.print(f"Name detection: [yellow]unavailable[/] — {reason}")

    from complydoc.config.loader import check_staleness

    warnings = check_staleness(config.pricing)  # type: ignore[attr-defined]
    if warnings:
        for warning in warnings:
            console.print(f"[yellow]Price provenance:[/] {warning.message}")
    else:
        console.print("Price provenance: [green]all enabled models verified recently[/]")


@app.command()
def models(
    match: Annotated[
        str | None,
        typer.Argument(help="Show only models whose id contains this."),
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="Show only one provider's models.")
    ] = None,
    show_all: Annotated[
        bool, typer.Option("--all", help="Include every model in the vendored price table.")
    ] = False,
    new: Annotated[
        int | None,
        typer.Option("--new", help="Show the N most recently released models instead."),
    ] = None,
    config_dir: ConfigOpt = None,
) -> None:
    """List the models available to price against, and where each price came from.

    The compared-by-default set is short on purpose: those are the prices someone
    has checked against the provider's own page. Behind them sits a table of
    several hundred more, any of which can be named with --model.
    """
    import datetime as dt

    from complydoc.cost.price_table import released_on, table_provenance

    config = _load(config_dir)
    pricing = config.pricing  # type: ignore[attr-defined]
    today = dt.date.today()

    chosen = list(pricing.models)
    filtered = bool(match or provider or new)
    if match:
        chosen = [m for m in chosen if match.lower() in m.id.lower()]
    if provider:
        chosen = [m for m in chosen if m.provider.lower() == provider.lower()]
    if new:
        # Newest first, and only models the catalogue dates. A model with no
        # release date is not assumed to be old; it is simply not ranked.
        dated = [(released_on(m.id), m) for m in chosen]
        chosen = [
            m
            for date, m in sorted(
                ((d, m) for d, m in dated if d), key=lambda pair: pair[0], reverse=True
            )
        ][:new]
    elif not filtered and not show_all:
        chosen = [m for m in chosen if m.enabled]

    if not chosen:
        errors.print("[yellow]No model matches.[/] Try [bold]complydoc models --all[/].")
        raise typer.Exit(code=1)

    table = Table(box=None, pad_edge=False)
    table.add_column("Model id")
    table.add_column("Provider")
    table.add_column("Input $/Mtok", justify="right")
    table.add_column("Batch", justify="right")
    table.add_column("Takes images")
    table.add_column("Released")
    table.add_column("Price from")

    for entry in chosen:
        if not entry.is_priced:
            state = "[yellow]no price[/]"
        elif entry.price_source == "imported":
            when = entry.imported_on.isoformat() if entry.imported_on else "unknown date"
            state = f"[dim]imported {when}[/]"
        else:
            age = entry.days_since_verified(today)
            if age is None:
                state = "[red]never verified[/]"
            elif age > pricing.staleness_warn_days:
                state = f"[red]verified {entry.last_verified} ({age}d)[/]"
            else:
                state = f"verified {entry.last_verified}"
        table.add_row(
            entry.id if entry.enabled else f"[dim]{entry.id}[/]",
            entry.provider,
            f"{entry.input_per_mtok_usd:g}" if entry.is_priced else "\u2014",
            f"{entry.batch_input_per_mtok_usd:g}" if entry.has_batch_price else "\u2014",
            "yes" if entry.supports_vision else "[dim]text only[/]",
            (released_on(entry.id) or "\u2014").__str__(),
            state,
        )
    console.print(table)

    source, imported_on, total = table_provenance()
    enabled = sum(1 for m in pricing.models if m.enabled)
    if not filtered and not show_all:
        console.print(
            f"\n[dim]Showing the {enabled} compared by default. {total} are in the "
            f"catalogue — [/][bold]complydoc models --new 15[/][dim] for the most "
            f"recently released, [/][bold]--all[/][dim], or search: "
            f"[/][bold]complydoc models gpt[/][dim].[/]"
        )
    console.print(
        f"\n[dim]Price one model with [/][bold]--model <id>[/][dim], repeat for several. "
        f"Imported prices come from {source} as of "
        f"{imported_on.isoformat() if imported_on else 'an unknown date'}; refresh with "
        f"[/][bold]make prices[/][dim].[/]"
    )


@app.command()
def extractors() -> None:
    """List the libraries that can read a PDF's text layer, and what each provides."""
    from complydoc.ingest.extractors.registry import DEFAULT_EXTRACTOR, all_extractors

    table = Table(box=None, pad_edge=False)
    table.add_column("Id")
    table.add_column("Boxes")
    table.add_column("Reads tables")
    table.add_column("Available")

    for engine in all_extractors():
        table.add_row(
            f"{engine.id}[dim] (default)[/]" if engine.id == DEFAULT_EXTRACTOR else engine.id,
            f"per {engine.granularity}",
            "yes" if engine.provides_tables else "[dim]no[/]",
            "yes" if engine.available() else "[yellow]no[/]",
        )
    console.print(table)
    console.print(
        "\n[dim]Pick one with [/][bold]--extractor <id>[/][dim], or read every page with a "
        "second and report where they differ: [/][bold]--compare-extractor <id>[/][dim].\n"
        "A signal needing what an extractor does not provide reports that it could not "
        "measure, rather than a number that means something else.[/]"
    )


@app.command()
def engines() -> None:
    """List the local OCR engines."""
    from complydoc.ingest.engines.registry import DEFAULT_ENGINE, all_engines

    table = Table(box=None, pad_edge=False)
    table.add_column("Id")
    table.add_column("Engine")
    table.add_column("Available")

    for engine in all_engines():
        reason = engine.unavailable_reason()
        table.add_row(
            f"{engine.id}[dim] (default)[/]" if engine.id == DEFAULT_ENGINE else engine.id,
            engine.name,
            "yes" if reason is None else f"[yellow]{reason}[/]",
        )
    console.print(table)
    console.print("\n[dim]Pick one with [/][bold]--ocr-engine <id>[/][dim].[/]")


@app.command("pricing-import")
def pricing_import(
    source: Annotated[
        Path | None,
        typer.Option("--from", help="Path to litellm's model_prices_and_context_window JSON."),
    ] = None,
    model: Annotated[
        list[str] | None,
        typer.Option("--model", "-m", help="Model id to import, repeatable."),
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="Import every vision model from one provider.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="Cap how many are printed.")] = 20,
) -> None:
    """Print pricing.yaml entries generated from litellm's price table.

    complydoc will not invent a price, so the shipped config leaves non-Anthropic
    models as empty templates. This fills them in from a maintained source and
    stamps each with the date you ran the import.

    litellm is not a runtime dependency and is never imported during an audit —
    only its data file is read, and only when you run this.
    """
    from complydoc.cost.pricing_import import (
        PricingImportError,
        load_table,
        select,
        to_yaml,
    )

    if not model and not provider:
        errors.print(
            "[bold red]Nothing selected.[/] Pass --model <id> (repeatable) or "
            "--provider <name>. Run with --provider anthropic to see the shape."
        )
        raise typer.Exit(code=2)

    try:
        table = load_table(source)
        chosen = select(table, ids=model, provider=provider, limit=limit)
    except PricingImportError as exc:
        errors.print(f"[bold red]Import failed[/] — {exc}")
        raise typer.Exit(code=2) from exc

    if not chosen:
        errors.print("[yellow]Nothing matched.[/] Try a different --provider or --model.")
        raise typer.Exit(code=1)

    errors.print(
        f"[dim]# {count(len(chosen), 'model')} from {len(table)} in the table. "
        f"Paste under `models:` in pricing.yaml.[/]"
    )
    print(to_yaml(chosen))


if __name__ == "__main__":  # pragma: no cover
    app()
