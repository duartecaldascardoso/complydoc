"""Is the document encrypted or password protected."""

from __future__ import annotations

from complydoc.difficulty.base import Measurement
from complydoc.difficulty.registry import signal
from complydoc.ingest.base import Document, DocumentFormat


@signal
class EncryptedSignal:
    id = "encrypted"
    name = "Encryption or password protection"
    unit = None
    why = "A password protected file cannot be opened by a pipeline at all."
    applies_to = frozenset({DocumentFormat.PDF})

    def measure(self, document: Document) -> Measurement:
        if not document.encrypted:
            return Measurement(value=False, display="not encrypted")
        if document.decrypted_with_empty_password:
            return Measurement(
                value=True,
                display="encrypted, empty password",
                detail={"opened": True, "empty_password": True},
            )
        return Measurement(
            value=True,
            display="encrypted, unreadable",
            detail={"opened": False},
        )
