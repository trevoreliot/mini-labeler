"""Sending sheets to the printer at true size, and choosing which PDF to print."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pymupdf

from md_labeler.config import PRINTER
from md_labeler.geometry import PAPER_SIZES, Paper, pt_to_mm

OUT_DIR = Path("out")
PAPER_TOLERANCE = 1.0  # mm

# CUPS media names for our paper sizes.
CUPS_MEDIA = {Paper.LETTER: "Letter", Paper.A4: "A4"}


@dataclass(frozen=True)
class PdfInfo:
    path: Path
    paper: Paper | None  # None if the page size is neither Letter nor A4
    pages: int
    modified: datetime

    def describe(self) -> str:
        paper = self.paper.value if self.paper else "unknown"
        return f"{self.modified:%Y-%m-%d %H:%M}  {paper:<7} {self.pages:>2}p  {self.path}"


def pdf_info(path: Path) -> PdfInfo:
    with pymupdf.open(path) as doc:
        rect = doc[0].rect
        size = (pt_to_mm(rect.width), pt_to_mm(rect.height))
        pages = doc.page_count
    paper = next(
        (p for p, (w, h) in PAPER_SIZES.items() if abs(size[0] - w) < PAPER_TOLERANCE and abs(size[1] - h) < PAPER_TOLERANCE),
        None,
    )
    return PdfInfo(path, paper, pages, datetime.fromtimestamp(path.stat().st_mtime))


def find_pdfs(root: Path = OUT_DIR) -> list[PdfInfo]:
    """Every PDF under `root`, newest first."""
    pdfs = [pdf_info(p) for p in root.rglob("*.pdf")] if root.is_dir() else []
    return sorted(pdfs, key=lambda i: i.modified, reverse=True)


def default_printer() -> str | None:
    if PRINTER:
        return PRINTER
    try:
        out = subprocess.run(["lpstat", "-d"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    _, _, name = out.partition(":")
    return name.strip() or None


# Grayscale, for proofs on plain paper. print-color-mode is standard IPP; ColorModel is the
# usual PPD option (the G600 driver's). Printers ignore options they don't know.
GRAY_OPTIONS = ("print-color-mode=monochrome", "ColorModel=Gray")


def lp_command(pdf: Path, paper: Paper, printer: str | None = None, copies: int = 1, gray: bool = False) -> list[str]:
    """The `lp` invocation that prints at true size.

    CUPS defaults to print-scaling=auto, which shrinks a full-size page to the printer's
    printable area (about 3% on the G600) even when the viewer is set to "Actual size".
    """
    cmd = ["lp"]
    if printer:
        cmd += ["-d", printer]
    cmd += ["-o", f"media={CUPS_MEDIA[paper]}", "-o", "print-scaling=none", "-o", "fit-to-page=false"]
    if gray:
        for opt in GRAY_OPTIONS:
            cmd += ["-o", opt]
    if copies > 1:
        cmd += ["-n", str(copies)]
    return [*cmd, "--", str(pdf)]


# --- Pickers -----------------------------------------------------------------
# Each returns the chosen path, or None if the user cancelled.


def pick_terminal(pdfs: list[PdfInfo]) -> Path | None:
    """fzf if installed, otherwise a numbered list."""
    if shutil.which("fzf"):
        return _pick_fzf(pdfs)
    return _pick_numbered(pdfs)


def _pick_fzf(pdfs: list[PdfInfo]) -> Path | None:
    lines = "\n".join(f"{i.describe()}\t{i.path}" for i in pdfs)
    result = subprocess.run(
        ["fzf", "--delimiter=\t", "--with-nth=1", "--no-sort", "--prompt=print> ", "--header=newest first"],
        input=lines,
        stdout=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return None
    return Path(result.stdout.rstrip("\n").split("\t")[-1])


def _pick_numbered(pdfs: list[PdfInfo]) -> Path | None:
    for n, info in enumerate(pdfs, 1):
        print(f"{n:>3}  {info.describe()}")
    choice = input("Print which? [number, blank to cancel] ").strip()
    if not choice:
        return None
    if not choice.isdigit() or not 1 <= int(choice) <= len(pdfs):
        raise ValueError(f"not a choice: {choice!r}")
    return pdfs[int(choice) - 1].path


def pick_gui(start: Path = OUT_DIR) -> Path | None:
    """A desktop file dialog: kdialog on KDE, else zenity."""
    start = start if start.is_dir() else Path.cwd()
    if shutil.which("kdialog"):
        cmd = ["kdialog", "--title", "Print labels", "--getopenfilename", str(start.resolve()), "PDF files (*.pdf)"]
    elif shutil.which("zenity"):
        cmd = ["zenity", "--file-selection", "--title=Print labels", f"--filename={start.resolve()}/", "--file-filter=*.pdf"]
    else:
        raise RuntimeError("no GUI file dialog found (install kdialog or zenity)")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    path = result.stdout.strip()
    return Path(path) if result.returncode == 0 and path else None
