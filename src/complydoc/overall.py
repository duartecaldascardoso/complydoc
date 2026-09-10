"""Global readiness: everything that decides whether a folder can be processed.

AI readiness is about content — can the text be got off the page at all. It is
the largest question and it is not the only one. A folder of perfectly legible
contracts that costs a fortune to run, or that cannot leave the building because
every page carries a national insurance number, is not ready either, and a score
that says 92 because the letters are crisp is answering a narrower question than
the one being asked.

So three factors, each 0 to 100, combined by weights in `readiness.yaml`:

`content`
    The AI readiness score already computed per document.
`cost`
    Whether the document forces the expensive path. Text on the page is nearly
    free to send to a model; a scan has to be recognised first, and a page that
    yields nothing has to be sent as an image, which costs an order of magnitude
    more.
`exposure`
    What is in it that should not leave. Weighted by severity and by how good
    the evidence is, so a confirmed card number counts for more than a name a
    model thought it saw.

A factor that was not measured is dropped and the remaining weights are
renormalised, exactly as the content score already does with its signals. The
result always says which factors it is made of, because a global score built
from one factor and a global score built from three are different claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from complydoc.config.schema import OverallConfig
from complydoc.readiness.scoring import band_label
from complydoc.report.models import AuditReport, DocumentReport
from complydoc.sensitive.base import EVIDENCE_ORDER, SEVERITY_WEIGHT

__all__ = ["Factor", "OverallReadiness", "band_of", "overall_readiness"]

_EVIDENCE_WEIGHT = {
    "confirmed": 1.0,
    "corroborated": 0.8,
    "pattern": 0.5,
    "model": 0.4,
}
"""How much a finding counts against a document, by how sure we are of it.

A model's guess is not nothing — it is the only evidence available for a
person's name — but it should not weigh the same as a checksum that passed.
"""


def band_of(value: float) -> str:
    """The same four bands the content score uses, so one scale reads across."""
    return band_label(value)


@dataclass(frozen=True, slots=True)
class Factor:
    """One input to the global score, and why it came out where it did."""

    key: str
    name: str
    score: float | None
    """None when this factor was not measured — the component did not run."""
    weight: float
    why: str

    @property
    def measured(self) -> bool:
        return self.score is not None


@dataclass(slots=True)
class OverallReadiness:
    """The folder, and every document in it, scored on all three factors."""

    score: float | None = None
    label: str = ""
    factors: list[Factor] = field(default_factory=list)
    bands: dict[str, int] = field(default_factory=dict)
    """How many documents fall in each band — the composition, not the average.

    The mean is one number and it hides the tail: a folder averaging 71 can
    still hold two documents nothing can be read from, and those two are the
    ones somebody has to deal with.
    """
    by_document: dict[str, float] = field(default_factory=dict)
    scored_documents: int = 0
    total_documents: int = 0

    @property
    def partial(self) -> bool:
        """True when some factor could not be measured for want of a component."""
        return any(not f.measured for f in self.factors)

    @property
    def measured_factors(self) -> list[Factor]:
        return [f for f in self.factors if f.measured]


def _content_score(document: DocumentReport) -> float | None:
    readiness = document.readiness
    if readiness is None or readiness.score is None:
        return None
    return float(readiness.score.value)


def _cost_score(document: DocumentReport, config: OverallConfig) -> float | None:
    """How far this document is from the cheap path.

    Not the price — the price depends on which model somebody picks and how
    many documents they have. This is the part the document itself decides:
    whether its text can be read off the page, had to be recognised, or cannot
    be had at all, in which case every page has to be sent as an image.
    """
    # From the cost estimate rather than the extracted text: the text is only
    # kept when the run was asked to keep it, and a factor that vanishes with
    # --no-extracted-text would silently reweight the score.
    if document.cost is None or not document.cost.pages:
        return None

    pages = document.cost.pages
    native = sum(1 for p in pages if p.text_source == "native")
    recognised = sum(1 for p in pages if p.text_source == "ocr")
    blank = len(pages) - native - recognised

    return round(
        (native * 100.0 + recognised * config.recognised_page_score + blank * 0.0) / len(pages),
        1,
    )


def _exposure_score(document: DocumentReport, config: OverallConfig) -> float | None:
    """What is in it that should not leave the building.

    Zero findings is 100. Every finding costs points in proportion to how
    serious it is and how sure we are of it, and the floor is zero — a document
    with forty confirmed card numbers is not more ready than one with twenty.
    """
    scan = document.sensitive
    if scan is None:
        return None

    exposure = 0.0
    for match in scan.matches:
        # A severity nobody recognises is not free: it counts as the lowest
        # rather than as nothing, so a config that grows a level does not
        # quietly stop costing anything.
        severity = float(SEVERITY_WEIGHT.get(match.severity, 1))
        evidence = _EVIDENCE_WEIGHT.get(match.evidence, 0.5)
        exposure += severity * evidence

    return round(max(0.0, 100.0 - exposure * config.points_per_exposure), 1)


def _document_score(
    document: DocumentReport, config: OverallConfig
) -> tuple[float | None, dict[str, float | None]]:
    """One document on all three factors, and the weighted result.

    Weights are renormalised over the factors that were actually measured, so a
    run without the cost component is not scored as though cost came out at
    nought.
    """
    parts: dict[str, float | None] = {
        "content": _content_score(document),
        "cost": _cost_score(document, config),
        "exposure": _exposure_score(document, config),
    }
    weights = {
        "content": config.content_weight,
        "cost": config.cost_weight,
        "exposure": config.exposure_weight,
    }

    measured = {k: v for k, v in parts.items() if v is not None and weights[k] > 0}
    if not measured:
        return None, parts

    divisor = sum(weights[k] for k in measured)
    value = sum(v * weights[k] for k, v in measured.items()) / divisor
    return round(value, 1), parts


def overall_readiness(report: AuditReport, config: OverallConfig) -> OverallReadiness:
    """The folder's global readiness, and the composition behind it."""
    result = OverallReadiness(total_documents=len(report.documents))
    if not config.enabled:
        return result

    scores: list[float] = []
    collected: dict[str, list[float]] = {"content": [], "cost": [], "exposure": []}

    for document in report.documents:
        value, parts = _document_score(document, config)
        for key, part in parts.items():
            if part is not None:
                collected[key].append(part)
        if value is None:
            continue
        scores.append(value)
        result.by_document[document.relative_path] = value
        result.bands[band_of(value)] = result.bands.get(band_of(value), 0) + 1

    result.scored_documents = len(scores)
    if scores:
        result.score = round(sum(scores) / len(scores), 1)
        result.label = band_of(result.score)

    def mean(key: str) -> float | None:
        values = collected[key]
        return round(sum(values) / len(values), 1) if values else None

    result.factors = [
        Factor(
            key="content",
            name="Content",
            score=mean("content"),
            weight=config.content_weight,
            why="Whether the text can be got off the page at all.",
        ),
        Factor(
            key="cost",
            name="Cost path",
            score=mean("cost"),
            weight=config.cost_weight,
            why=(
                "Text already on the page is nearly free to send to a model. "
                "A scan has to be recognised first, and a page that yields "
                "nothing has to go as an image, which costs far more."
            ),
        ),
        Factor(
            key="exposure",
            name="Exposure",
            score=mean("exposure"),
            weight=config.exposure_weight,
            why=(
                "What these documents carry that should not leave, weighted by "
                "severity and by how good the evidence for each finding is."
            ),
        ),
    ]
    return result


def evidence_weight(evidence: str) -> float:
    """Exposed for the report, so the page can explain the weighting it used."""
    return _EVIDENCE_WEIGHT.get(evidence, 0.5)


assert set(_EVIDENCE_WEIGHT) == set(EVIDENCE_ORDER), "every tier needs a weight"
