from __future__ import annotations

import shlex
import subprocess
from datetime import datetime
from pathlib import Path

import typer

from md_labeler import config
from md_labeler.albumlist import AlbumEntry, read_album_list, write_album_list
from md_labeler.fetch import WORK_DIR, fetch_entry
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


SELECTIONS_DIR = Path("selections")
LABEL_PAGES = 2  # each batch of albums fills this many pages


@app.command()
def pick(
    music_root: Path = typer.Option(config.MUSIC_ROOT, help="Library laid out as <root>/<artist>/<album>."),
    paper: Paper = Paper.LETTER,
    out: Path | None = typer.Option(None, help=f"Album list to write. Default: {SELECTIONS_DIR}/<date-time>.txt"),
    fetch: bool = typer.Option(True, help="Run the fetch stage on the selection afterwards."),
) -> None:
    """Choose albums in a window until the label sheets are full, then fetch them."""
    from md_labeler.picker import pick_albums  # Qt is only needed here

    slots = {p: capacity(SheetConfig(paper=p), LABEL_PAGES) for p in Paper}
    result = pick_albums(music_root, slots, paper)
    if not result:
        typer.echo("Cancelled.")
        raise typer.Exit(1)
    entries, paper = result
    out = out or SELECTIONS_DIR / f"{datetime.now():%Y-%m-%d-%H%M%S}.txt"
    write_album_list(out, entries)
    typer.echo(f"{len(entries)} album(s), {paper.value}: {out}")
    for e in entries:
        typer.echo(f"  {e.artist} - {e.album}")
    if fetch:
        _fetch_all(entries, force=False)


@app.command("fetch")
def fetch_cmd(
    album_list: Path = typer.Argument(..., exists=True, dir_okay=False, help="Album list (one 'Artist - Album' per line)."),
    force: bool = typer.Option(False, help="Re-read albums that already have an album.json (discards curated edits)."),
) -> None:
    """Gather metadata and cover art into work/<album>/, from local files where possible."""
    _fetch_all(read_album_list(album_list), force)


def _fetch_all(entries: list[AlbumEntry], force: bool) -> None:
    typer.echo(f"\nFetching into {WORK_DIR}/:")
    for entry in entries:
        r = fetch_entry(entry, force=force)
        a = r.album
        art = f"art {a.art_px}px ({a.art_source})" if a.art_file else "no art"
        state = "kept existing" if r.skipped else f"{len(a.tracks)} tracks, {art}"
        needs = f"  -> needs from MusicBrainz: {', '.join(a.needs)}" if a.needs else ""
        typer.echo(f"  {r.dir.name}: {state}{needs}")
