"""Temporary: why the segmenting reader reads nothing on Linux."""

import importlib.metadata as md
import logging

logging.basicConfig(level=logging.DEBUG)

for pkg in ("unstructured", "pdfminer.six", "unstructured-inference", "pillow", "lxml"):
    try:
        print("VERSION", pkg, md.version(pkg))
    except Exception as exc:
        print("VERSION", pkg, "absent", exc)

from unstructured.partition.pdf import partition_pdf

for strategy in ("fast", "auto"):
    try:
        els = partition_pdf("tests/fixtures/two_column.pdf", strategy=strategy)
        print("RESULT", strategy, len(els), [str(e)[:40] for e in els[:2]])
    except Exception as exc:
        print("RESULT", strategy, "raised", type(exc).__name__, exc)

from unstructured.partition.pdf import extractable_elements

try:
    with open("tests/fixtures/two_column.pdf", "rb") as fh:
        got = extractable_elements(file=fh)
    print("EXTRACTABLE", sum(len(p) for p in got))
except Exception as exc:
    print("EXTRACTABLE raised", type(exc).__name__, exc)
