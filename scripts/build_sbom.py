"""Write a CycloneDX SBOM for what a complydoc install actually pulls in.

Built from `uv.lock` rather than from whatever happens to be installed, so the
bill of materials describes the release and not the machine that made it. The
dev group is excluded and both optional extras are included, because the extras
are what a user installing OCR and NER would get.

The root component's version is stamped in afterwards: the package version is
declared once in `complydoc/__init__.py` and read from there by the build
backend, which SBOM tooling cannot resolve on its own.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def package_version() -> str:
    text = (ROOT / "src" / "complydoc" / "__init__.py").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no __version__ in src/complydoc/__init__.py")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "complydoc-sbom.json")
    arguments = parser.parse_args()

    version = package_version()
    arguments.out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as scratch:
        requirements = Path(scratch) / "requirements.txt"
        subprocess.run(
            [
                "uv",
                "export",
                "--frozen",
                "--no-dev",
                "--all-extras",
                "--no-emit-project",
                "--format",
                "requirements-txt",
                "-o",
                str(requirements),
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run(
            [
                "uv",
                "run",
                "cyclonedx-py",
                "requirements",
                str(requirements),
                "--pyproject",
                str(ROOT / "pyproject.toml"),
                "--of",
                "json",
                "--output-reproducible",
                "-o",
                str(arguments.out),
            ],
            cwd=ROOT,
            check=True,
        )

    document = json.loads(arguments.out.read_text(encoding="utf-8"))
    document["metadata"]["component"]["version"] = version
    arguments.out.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    component = document["metadata"]["component"]
    print(
        f"{arguments.out}: {component['name']} {version}, "
        f"{len(document['components'])} dependencies"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
