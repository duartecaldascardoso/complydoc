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
    why = "Rules that find a field by how it looks break across many fonts."
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
            display=f"{len(fonts)} fonts",
            detail={"fonts": sorted(fonts)},
        )


@signal
class FontsEmbeddedSignal:
    id = "fonts_embedded"
    name = "Fonts embedded"
    unit = None
    why = "A font neither embedded nor standard is substituted, shifting the layout."
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
                else f"{missing} pages use a non-standard font"
            ),
            detail={"pages_checked": len(known), "pages_with_missing_fonts": missing},
        )
