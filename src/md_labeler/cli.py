from __future__ import annotations

from pathlib import Path

import typer

from md_labeler.geometry import Paper
from md_labeler.layout import SheetConfig, album_requests, capacity, pack
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
