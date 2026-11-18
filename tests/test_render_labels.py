import io

import pymupdf
import pytest
from PIL import Image

from md_labeler.geometry import Rect
from md_labeler.layout import SheetConfig
from md_labeler.models import Album, Track
from md_labeler.render import labels as L
from md_labeler.render.art import art_jpeg
from md_labeler.render.run import render_albums
from md_labeler.render.text import MIN_HSCALE, fit, register_fonts, width_mm
from md_labeler.style import Style, contrast, default_style, extract_palette

register_fonts()


def _work(tmp_path, name, tracks=10, title="Album", artist="Artist", style: Style | None = None, cover_px=900):
    d = tmp_path / name
    d.mkdir()
    shade = sum(map(ord, name)) % 200  # distinct covers: the PDF stores identical images once
    Image.new("RGB", (cover_px, cover_px), (30, shade, 160)).save(d / "cover.jpg")
    album = Album(artist, title, "2001", [Track(i, f"Song number {i}", 200) for i in range(1, tracks + 1)], art_file="cover.jpg", art_px=cover_px)
    album.save(d / "album.json")
    if style:
        style.save(d / "style.json")
    return d


def test_style_problems():
    assert Style().problems() == []
    bad = Style(spine_font="Comic", bg="black", front="tile", columns=5)
    assert len(bad.problems()) == 4
    assert any("contrast" in p for p in Style(fg="#222222", bg="#111111").problems())


def test_default_style_is_readable():
    mid_tones = [(30, g, 160) for g in range(0, 256, 15)] + [(g, g, g) for g in range(90, 140, 5)]
    for color in [(250, 240, 200), (10, 10, 30), (200, 30, 30), *mid_tones]:
        palette = extract_palette(Image.new("RGB", (50, 50), color))
        s = default_style(palette)
        assert contrast(s.fg, s.bg) >= 4.5 and s.problems() == []


def test_fit_shrinks_then_squeezes_then_shortens():
    font = "BarlowCondensed-SemiBold"
    assert fit("ABC", font, 50, 7.5, 5).size == 7.5
    long = "A VERY LONG ARTIST NAME · AN EVEN LONGER ALBUM TITLE (DELUXE)"
    f = fit(long, font, 56, 7.5, 5)
    assert f.size < 7.5 and not f.shortened
    f = fit(long * 3, font, 56, 7.5, 5)
    assert f.shortened and f.hscale == MIN_HSCALE and width_mm(f.text, font, f.size, f.hscale) <= 56


def test_art_jpeg_is_exact_size_at_300dpi(tmp_path):
    Image.new("RGB", (1000, 1000)).save(tmp_path / "c.png")
    img = Image.open(io.BytesIO(art_jpeg(tmp_path / "c.png", 39, 56)))
    assert img.format == "JPEG" and img.size == (461, 661)


@pytest.mark.parametrize(("tracks", "columns"), [(10, 1), (13, 1), (24, 2)])
def test_track_list_prefers_fewer_columns(tracks, columns):
    ctx = L.AlbumContext(Album("A", "B", tracks=[Track(i, f"Song {i}", 180) for i in range(1, tracks + 1)]), Style(), None)
    layout = L._plan(L._rows(ctx), Style().text_font, Rect(2, 11.5, 66, 36.5), [1, 2, 3])
    assert layout.columns == columns


def test_multi_disc_rows_get_headings():
    tracks = [Track(1, "a", disc=1), Track(1, "b", disc=2)]
    rows = L._rows(L.AlbumContext(Album("A", "B", tracks=tracks), Style(), None))
    assert [r.title for r in rows] == ["DISC 1", "a", "DISC 2", "b"]


def test_render_albums_end_to_end(tmp_path):
    dirs = [
        _work(tmp_path, "plain"),
        _work(tmp_path, "styled", style=Style(front="fill", numbering="none", durations=False)),
        _work(tmp_path, "long", title="An Extremely Long Album Title That Will Never Fit On A Spine " * 2, tracks=40, cover_px=400),
    ]
    pdf, proofs, albums = render_albums(dirs, SheetConfig(), tmp_path / "out" / "labels.pdf")
    assert pdf.exists() and len(proofs) == 1
    assert [a.styled for a in albums] == [False, True, False]
    assert (dirs[0] / "palette.json").exists()
    long = albums[2].ctx.warnings
    assert any("spine text" in w for w in long)
    assert any("may print soft" in w for w in long)
    assert not albums[0].ctx.warnings
    with pymupdf.open(pdf) as doc:
        assert len(doc[0].get_images()) == 6  # disc + front for each album


def test_unknown_font_stops_render(tmp_path):
    d = _work(tmp_path, "x", style=Style(title_font="Nope"))
    with pytest.raises(ValueError, match="unknown fonts"):
        render_albums([d], SheetConfig(), tmp_path / "o.pdf")
