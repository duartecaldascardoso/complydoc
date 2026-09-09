"""Command line interface.

Four commands. `audit` runs everything; `cost`, `difficulty` and `sensitive` run
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
    `difficulty`, `sensitive`, `models`, `schema`, `doctor`.
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
        "--page-images",
        help="Embed a picture of each page beside what was extracted from it. "
        "Off by default: it puts real document content into the report.",
    ),
]
ExtractedTextOpt = Annotated[
    bool,
    typer.Option(
        "--extracted-text",
        help="Include the text read off each page, so extraction quality can be "
        "checked. Off by default: the extracted text is the document.",
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
PrintJsonOpt = Annotated[
    bool,
    typer.Option(
        "--print-json",
        help="Write the JSON report to stdout and nothing else, for piping into "
        "another tool or an agent. Progress goes to stderr.",
    ),
]
QuietOpt = Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress output.")]
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


def _emit(report: AuditReport, config: object, out: Path, name: str, quiet: bool) -> None:
    json_path = write_json(report, out / f"{name}.json").resolve()
    html_path = write_html(report, config, out / f"{name}.html").resolve()  # type: ignore[arg-type]
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
    if aggregate.mean_difficulty_score is not None:
        table.add_row("Mean difficulty", f"{aggregate.mean_difficulty_score}/100")
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
            f"\n[yellow]{len(important)} important limitation(s)[/] — see the report before "
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
    page_images: bool = False,
    extracted_text: bool = False,
    ocr_compare: bool = False,
    print_json: bool = False,
) -> None:
    offline.arm()
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
    if page_images:
        errors.print(
            "[bold yellow]--page-images is set.[/] The HTML report will contain a picture "
            "of every page, so it carries the document content itself."
        )
    if extracted_text or ocr_compare:
        errors.print(
            "[bold yellow]--extracted-text is set.[/] The reports will contain the text read "
            "off every page, which is the document content in full."
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
            progress=progress if not quiet else None,
        )
    except UnknownModelError as exc:
        errors.print(f"[bold red]Unknown model[/] — {exc}\n\nRun 'complydoc models' to list them.")
        raise typer.Exit(code=2) from exc
    if not quiet:
        _summary(report)
    _emit(report, config, out, name, quiet)
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
    page_images: PageImagesOpt = False,
    extracted_text: ExtractedTextOpt = False,
    ocr_compare: OcrCompareOpt = False,
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = True,
    recurse: RecurseOpt = True,
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
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = True,
    recurse: RecurseOpt = True,
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
    )


@app.command()
def difficulty(
    target: TargetArg,
    out: OutDirOpt = DEFAULT_OUT,
    name: NameOpt = "complydoc-difficulty",
    extracted_text: ExtractedTextOpt = False,
    ocr_compare: OcrCompareOpt = False,
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = True,
    recurse: RecurseOpt = True,
    print_json: PrintJsonOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Measure extraction difficulty signals only."""
    _run(
        target,
        ("difficulty",),
        out,
        name,
        config_dir,
        ocr,
        recurse,
        quiet,
        extracted_text=extracted_text,
        ocr_compare=ocr_compare,
        print_json=print_json,
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
    page_images: PageImagesOpt = False,
    extracted_text: ExtractedTextOpt = False,
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = True,
    recurse: RecurseOpt = True,
    print_json: PrintJsonOpt = False,
    quiet: QuietOpt = False,
) -> None:
    """Scan for UK GDPR relevant identifiers only."""
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
                    "components_run": "list of cost | difficulty | sensitive",
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
                    "difficulty.signals[]": "id, value, rating, weight, why, status",
                    "difficulty.score": "value 0-100, higher is easier; label; low_confidence",
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
def models(config_dir: ConfigOpt = None) -> None:
    """List the models available to price against, and how current each price is."""
    import datetime as dt

    config = _load(config_dir)
    pricing = config.pricing  # type: ignore[attr-defined]
    today = dt.date.today()

    table = Table(box=None, pad_edge=False)
    table.add_column("Model id")
    table.add_column("Provider")
    table.add_column("Input $/Mtok", justify="right")
    table.add_column("Vision formula")
    table.add_column("Verified")

    for entry in pricing.models:
        if not entry.enabled:
            state = "[dim]disabled, no price[/]"
        elif not entry.is_priced:
            state = "[yellow]no price[/]"
        else:
            age = entry.days_since_verified(today)
            if age is None:
                state = "[red]never[/]"
            elif age > pricing.staleness_warn_days:
                state = f"[red]{entry.last_verified} ({age}d)[/]"
            else:
                state = f"{entry.last_verified}"
        table.add_row(
            entry.id if entry.enabled else f"[dim]{entry.id}[/]",
            entry.provider,
            f"{entry.input_per_mtok_usd:g}" if entry.is_priced else "—",
            entry.vision_formula or "—",
            state,
        )
    console.print(table)
    console.print(
        "\nPrice one model with [bold]--model <id>[/], repeat the flag for several. "
        "Add more with [bold]complydoc pricing-import[/]."
    )


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
        f"[dim]# {len(chosen)} model(s) from {len(table)} in the table. "
        f"Paste under `models:` in pricing.yaml.[/]"
    )
    print(to_yaml(chosen))


if __name__ == "__main__":  # pragma: no cover
    app()
