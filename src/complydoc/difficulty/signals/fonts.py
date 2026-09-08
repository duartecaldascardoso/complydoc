"""Font variety and whether fonts are embedded."""

from __future__ import annotations

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document, DocumentFormat


@signal
class FontCountSignal:
    id = "font_count"
    name = "Distinct fonts"
    unit = "fonts"
    why = (
        "Rules that find a field by how it looks — bold labels, a larger heading — break "
        "when a document mixes many fonts, because the same visual role is expressed "
        "differently in different places."
    )
    applies_to = frozenset({DocumentFormat.PDF, DocumentFormat.DOCX})

    def measure(self, document: Document) -> Measurement:
        fonts: set[str] = set()
        for page in document.pages:
            fonts |= page.fonts
        if not fonts:
            return Measurement.na(
                "no font information was recorded, which is expected on a scanned "
                "document where the page carries no text objects"
            )
        return Measurement(
            value=len(fonts),
            display=f"{len(fonts)} distinct font(s)",
            detail={"fonts": sorted(fonts)},
        )


@signal
class FontsEmbeddedSignal:
    id = "fonts_embedded"
    name = "Fonts embedded"
    unit = None
    why = (
        "A font that is not embedded and is not one of the standard PDF fonts is "
        "substituted at display time, so character widths shift and text that looked "
        "aligned on one machine extracts in a different order on another."
    )
    applies_to = frozenset({DocumentFormat.PDF})

    def measure(self, document: Document) -> Measurement:
        known = [p.embedded_fonts for p in document.pages if p.embedded_fonts is not None]
        if not known:
            return Measurement.na(
                "no page declared any fonts, so there is nothing to embed. This is normal "
                "for a scanned document"
            )
        all_embedded = all(known)
        missing = sum(1 for value in known if not value)
        return Measurement(
            value=all_embedded,
            display=(
                "all fonts embedded or standard"
                if all_embedded
                else f"{missing} page(s) rely on a font that is neither embedded nor standard"
            ),
            detail={"pages_checked": len(known), "pages_with_missing_fonts": missing},
        )
