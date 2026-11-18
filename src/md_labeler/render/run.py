"""The render stage: work/<slug>/ for each album -> one label PDF + PNG proofs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from md_labeler.geometry import art_px_needed
from md_labeler.layout import Placement, SheetConfig, album_requests, pack
from md_labeler.models import Album
from md_labeler.render.labels import AlbumContext, paint
from md_labeler.render.proof import write_proofs
from md_labeler.render.sheet import Page, render_pdf
from md_labeler.render.text import register_fonts
from md_labeler.style import Style, default_style, ensure_palette


@dataclass
class AlbumRender:
    dir: Path
    ctx: AlbumContext
    styled: bool  # True if style.json existed; False means a palette-based default was used


def load_album(work_dir: Path) -> AlbumRender:
    album = Album.load(work_dir / "album.json")
    palette = ensure_palette(work_dir, album.art_file)
    style_path = work_dir / "style.json"
    style = Style.load(style_path) if style_path.exists() else default_style(palette)
    cover = work_dir / album.art_file if album.art_file and (work_dir / album.art_file).exists() else None
    ctx = AlbumContext(album, style, cover)
    for p in style.problems():
        ctx.warn(f"style: {p}")
    if cover is None:
        ctx.warn("no cover art; disc and front use text instead")
    elif (album.art_px or 0) < art_px_needed():
        ctx.warn(f"cover is {album.art_px}px, under {art_px_needed()}px: may print soft")
    if album.needs_review:
        ctx.warn("MusicBrainz match needs review (see candidates in album.json)")
    return AlbumRender(work_dir, ctx, style_path.exists())


def render_albums(work_dirs: list[Path], cfg: SheetConfig, out: Path, guides: bool = False) -> tuple[Path, list[Path], list[AlbumRender]]:
    register_fonts()
    albums = [load_album(d) for d in work_dirs]
    bad_fonts = [a for a in albums if any("is not in assets/fonts" in w for w in a.ctx.warnings)]
    if bad_fonts:
        raise ValueError(f"unknown fonts in style.json for: {', '.join(a.dir.name for a in bad_fonts)}")

    def painter(c, frame: Page, pl: Placement) -> None:
        paint(c, frame, pl.kind, albums[pl.album].ctx)

    placements = pack(album_requests(len(albums)), cfg)
    pdf = render_pdf(placements, cfg, out, painter, show_guides=guides)
    return pdf, write_proofs(pdf), albums
