from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

import typer

from md_labeler.geometry import Paper
from md_labeler.layout import SheetConfig, album_requests, capacity, pack
from md_labeler.printing import OUT_DIR, default_printer, find_pdfs, lp_command, pdf_info, pick_gui, pick_terminal
from md_labeler.render.proof import write_proofs
from md_labeler.render.sheet import render_pdf

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """Print-ready MiniDisc labels."""


@app.command()
def testsheet(
    paper: Paper = Paper.LETTER,
    pages: int = typer.Option(2, min=1, help="Fill this many pages with as many albums as fit."),
    albums: int | None = typer.Option(None, min=1, help="Lay out exactly this many albums instead."),
    out: Path = Path("out/testsheet.pdf"),
) -> None:
    """Lay out placeholder labels with cut and safe guides, to check sizes after printing."""
    cfg = SheetConfig(paper=paper)
    albums = albums or capacity(cfg, pages)
    placements = pack(album_requests(albums), cfg)
    pdf = render_pdf(placements, cfg, out, show_guides=True)
    proofs = write_proofs(pdf)
    typer.echo(f"{pdf}  ({albums} albums, {len(proofs)} page(s); proofs: {', '.join(map(str, proofs))})")


@app.command("print")
def print_(
    pdf: Path | None = typer.Argument(None, exists=True, dir_okay=False, help="PDF to print. Omit to pick one."),
    gui: bool = typer.Option(False, "--gui", help="Pick the file in a desktop file dialog."),
    printer: str | None = typer.Option(None, help="CUPS printer name. Default: config.PRINTER or the system default."),
    copies: int = typer.Option(1, min=1),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show the lp command without printing."),
) -> None:
    """Print a sheet at true size (no CUPS auto-scaling). Paper size is read from the PDF."""
    if pdf is None:
        if gui:
            pdf = pick_gui()
        else:
            pdfs = find_pdfs()
            if not pdfs:
                raise typer.BadParameter(f"no PDFs under {OUT_DIR}/ — pass a file path instead")
            pdf = pick_terminal(pdfs)
        if pdf is None:
            raise typer.Exit()

    info = pdf_info(pdf)
    if info.paper is None:
        raise typer.BadParameter(f"{pdf} is not a Letter or A4 page; refusing to guess the paper size")
    cmd = lp_command(pdf, info.paper, printer or default_printer(), copies)
    typer.echo(f"{pdf}: {info.paper.value}, {info.pages} page(s)")
    typer.echo(" ".join(shlex.quote(c) for c in cmd))
    if dry_run:
        return
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)
