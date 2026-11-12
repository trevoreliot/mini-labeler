"""PNG proofs of a rendered PDF, for quick visual review."""

from __future__ import annotations

from pathlib import Path

import pymupdf

PROOF_DPI = 150


def write_proofs(pdf: Path, dpi: int = PROOF_DPI) -> list[Path]:
    paths = []
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc):
            path = pdf.with_name(f"{pdf.stem}-proof-{i + 1}.png")
            page.get_pixmap(dpi=dpi).save(path)
            paths.append(path)
    return paths
