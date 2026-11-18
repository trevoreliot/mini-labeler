from __future__ import annotations

import shlex
import subprocess
from datetime import datetime
from pathlib import Path

import typer

from md_labeler import config
from md_labeler.albumlist import AlbumEntry, read_album_list, read_paper, write_album_list
from md_labeler.fetch import WORK_DIR, fetch_entry
from md_labeler.fetch.http import Http
from md_labeler.geometry import Paper
from md_labeler.layout import SheetConfig, album_requests, capacity, pack
from md_labeler.models import slugify
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
    printer: str | None = typer.Option(None, help="CUPS printer name. Default: $MD_LABELER_PRINTER or the system default."),
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
    music_root: Path = typer.Option(config.MUSIC_ROOT, help="Library laid out as <root>/<artist>/<album>. Default: $MD_LABELER_MUSIC_ROOT."),
    paper: Paper = Paper.LETTER,
    out: Path | None = typer.Option(None, help=f"Album list to write. Default: {SELECTIONS_DIR}/<date-time>.txt"),
    fetch: bool = typer.Option(True, help="Run the fetch stage on the selection afterwards."),
    offline: bool = typer.Option(False, help="Use local files only; no MusicBrainz / Cover Art Archive."),
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
    write_album_list(out, entries, paper.value)
    typer.echo(f"{len(entries)} album(s), {paper.value}: {out}")
    for e in entries:
        typer.echo(f"  {e.artist} - {e.album}")
    if fetch:
        _fetch_all(entries, force=False, offline=offline)


@app.command("fetch")
def fetch_cmd(
    album_list: Path = typer.Argument(..., exists=True, dir_okay=False, help="Album list (one 'Artist - Album' per line)."),
    force: bool = typer.Option(False, help="Re-read albums that already have an album.json (discards curated edits)."),
    offline: bool = typer.Option(False, help="Use local files only; no MusicBrainz / Cover Art Archive."),
    refresh: bool = typer.Option(False, help="Ignore cached HTTP responses."),
) -> None:
    """Gather metadata and cover art into work/<album>/: local files first, then online for missing/low-res art."""
    _fetch_all(read_album_list(album_list), force, offline, refresh)


def _fetch_all(entries: list[AlbumEntry], force: bool, offline: bool = False, refresh: bool = False) -> None:
    http = None if offline else Http(refresh=refresh)
    typer.echo(f"\nFetching into {WORK_DIR}/{' (offline)' if offline else ''}:")
    for entry in entries:
        r = fetch_entry(entry, force=force, http=http)
        a = r.album
        art = f"art {a.art_px}px ({a.art_source})" if a.art_file else "no art"
        state = f"{'kept existing, ' if r.skipped else ''}{len(a.tracks)} tracks, {art}"
        typer.echo(f"  {r.dir.name}: {state}")
        for note in r.online:
            typer.echo(f"      online {note}")
        if a.needs or a.needs_review:
            todo = [*a.needs, *(["review match"] if a.needs_review else [])]
            typer.echo(f"      still needs: {', '.join(todo)}")


@app.command()
def render(
    selection: Path | None = typer.Argument(None, exists=True, dir_okay=False, help=f"Album list. Default: newest in {SELECTIONS_DIR}/."),
    paper: Paper | None = typer.Option(None, help="Default: the paper recorded in the list, else letter."),
    guides: bool = typer.Option(False, help="Also draw cut/bleed/safe outlines (for checking, not printing)."),
    out: Path | None = typer.Option(None, help=f"PDF to write. Default: {OUT_DIR}/<list name>/labels.pdf"),
) -> None:
    """Lay out and draw every label for the albums in a list, from their work/ folders."""
    from md_labeler.render.run import render_albums

    if selection is None:
        lists = sorted(SELECTIONS_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime)
        if not lists:
            raise typer.BadParameter(f"no album lists in {SELECTIONS_DIR}/; run `mdl pick` or pass a list")
        selection = lists[-1]
    entries = read_album_list(selection)
    dirs = [WORK_DIR / slugify(e.artist, e.album) for e in entries]
    missing = [d.name for d in dirs if not (d / "album.json").exists()]
    if missing:
        raise typer.BadParameter(f"not fetched yet: {', '.join(missing)}; run `mdl fetch {selection}`")
    paper = paper or Paper(read_paper(selection) or Paper.LETTER.value)
    out = out or OUT_DIR / selection.stem / "labels.pdf"

    pdf, proofs, albums = render_albums(dirs, SheetConfig(paper=paper), out, guides)
    typer.echo(f"{pdf}  ({len(albums)} albums, {paper.value}, {len(proofs)} page(s))")
    typer.echo(f"proofs: {', '.join(map(str, proofs))}")
    for a in albums:
        flags = "" if a.styled else "  [default style: no style.json yet]"
        typer.echo(f"  {a.dir.name}{flags}")
        for w in a.ctx.warnings:
            typer.echo(f"      ! {w}")
