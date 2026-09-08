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
    no_args_is_help=True,
    help=(
        "Audit a folder of business documents offline: what they would cost to process "
        "with an LLM, how hard they are to extract from, and what sensitive information "
        "they contain. No document content ever leaves this machine."
    ),
)
console = Console()
errors = Console(stderr=True)

TargetArg = Annotated[Path, typer.Argument(help="A file or folder to audit.")]
OutDirOpt = Annotated[Path, typer.Option("--out", "-o", help="Directory for the reports.")]
ConfigOpt = Annotated[
    Path | None, typer.Option("--config-dir", help="Override the config directory.")
]
OcrOpt = Annotated[bool, typer.Option("--ocr/--no-ocr", help="Read scanned pages with local OCR.")]
RecurseOpt = Annotated[
    bool, typer.Option("--recurse/--no-recurse", help="Descend into subfolders.")
]
NameOpt = Annotated[str, typer.Option("--name", help="Base filename for the reports.")]
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
    json_path = write_json(report, out / f"{name}.json")
    html_path = write_html(report, config, out / f"{name}.html")  # type: ignore[arg-type]
    if not quiet:
        console.print(f"\n[green]JSON[/]  {json_path}")
        console.print(f"[green]HTML[/]  {html_path}")


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
) -> None:
    offline.arm()
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
            recurse=recurse,
            progress=progress if not quiet else None,
        )
    except UnknownModelError as exc:
        errors.print(f"[bold red]Unknown model[/] — {exc}\n\nRun 'complydoc models' to list them.")
        raise typer.Exit(code=2) from exc
    if not quiet:
        _summary(report)
    _emit(report, config, out, name, quiet)


@app.command()
def audit(
    target: TargetArg,
    out: OutDirOpt = Path("reports"),
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
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = False,
    recurse: RecurseOpt = True,
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
    )


@app.command()
def cost(
    target: TargetArg,
    out: OutDirOpt = Path("reports"),
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
    ocr: OcrOpt = False,
    recurse: RecurseOpt = True,
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
    )


@app.command()
def difficulty(
    target: TargetArg,
    out: OutDirOpt = Path("reports"),
    name: NameOpt = "complydoc-difficulty",
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = False,
    recurse: RecurseOpt = True,
    quiet: QuietOpt = False,
) -> None:
    """Measure extraction difficulty signals only."""
    _run(target, ("difficulty",), out, name, config_dir, ocr, recurse, quiet)


@app.command()
def sensitive(
    target: TargetArg,
    out: OutDirOpt = Path("reports"),
    name: NameOpt = "complydoc-sensitive",
    reveal: Annotated[
        bool,
        typer.Option(
            "--reveal",
            help="Print sensitive values in full. Off by default, and the report says so.",
        ),
    ] = False,
    config_dir: ConfigOpt = None,
    ocr: OcrOpt = False,
    recurse: RecurseOpt = True,
    quiet: QuietOpt = False,
) -> None:
    """Scan for UK GDPR relevant identifiers only."""
    _run(target, ("sensitive",), out, name, config_dir, ocr, recurse, quiet, reveal=reveal)


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
