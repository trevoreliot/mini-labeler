"""Draws each label's content in its own frame: the cut box spans (0, 0)–(w, h) mm, y down."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from md_labeler.geometry import LABELS, LabelKind, Rect, mm_to_pt
from md_labeler.models import Album
from md_labeler.render.art import art_jpeg
from md_labeler.render.sheet import Page
from md_labeler.render.text import ELLIPSIS, cap_mm, descent_mm, draw, ellipsize, fit, fmt_duration, width_mm
from md_labeler.style import Style, mix

# Type sizes, pt
SPINE_MAX, SPINE_MIN = 7.5, 5.0
TRACK_MAX, TRACK_MIN = 7.0, 4.5
BACK_TITLE_MAX, BACK_TITLE_MIN = 10.0, 6.0
BACK_META = 5.5
PANEL_TITLE_MAX, PANEL_TITLE_MIN = 16.0, 7.0
PANEL_META_MAX, PANEL_META_MIN = 8.0, 5.0
LINE_SPACING = 1.25  # track list line height, as a multiple of the type size
COLUMN_GAP = 3.0  # mm
COLUMN_COST = 1.0  # pt of type size an extra column must gain to be worth it
PANEL_ART_GAP = 1.5  # mm between the cover and the text in the front panel


@dataclass
class AlbumContext:
    album: Album
    style: Style
    cover: Path | None
    warnings: list[str] = field(default_factory=list)

    @property
    def year(self) -> str | None:
        return self.album.original_year or self.album.year

    def cased(self, text: str) -> str:
        return text.upper() if self.style.uppercase else text

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)


def paint(c: Canvas, frame: Page, kind: LabelKind, ctx: AlbumContext) -> None:
    {
        LabelKind.DISC: paint_disc,
        LabelKind.CASE_FRONT: paint_front,
        LabelKind.CASE_BACK: paint_back,
        LabelKind.DISC_SPINE: paint_spine,
        LabelKind.CASE_SPINE: paint_spine,
    }[kind](c, frame, kind, ctx)


# --- Shared ----------------------------------------------------------------------


def _bleed_box(kind: LabelKind) -> Rect:
    spec = LABELS[kind]
    return Rect(0, 0, spec.w, spec.h).outset(spec.bleed)


def _fill(c: Canvas, frame: Page, r: Rect, color: str) -> None:
    c.setFillColor(HexColor(color))
    c.rect(*frame.pt(r.x, r.y1), mm_to_pt(r.w), mm_to_pt(r.h), stroke=0, fill=1)


def _art(c: Canvas, frame: Page, cover: Path, r: Rect, fx: float = 0.5, fy: float = 0.5) -> None:
    img = ImageReader(io.BytesIO(art_jpeg(cover, r.w, r.h, fx, fy)))
    c.drawImage(img, *frame.pt(r.x, r.y1), mm_to_pt(r.w), mm_to_pt(r.h))


def _text(c: Canvas, frame: Page, x: float, baseline: float, segments, font: str, size: float, hscale: float = 1.0, align: str = "left") -> None:
    if align != "left":
        w = sum(width_mm(t, font, size, hscale) for t, _ in segments)
        x -= w if align == "right" else w / 2
    draw(c, *frame.pt(x, baseline), segments, font, size, hscale)


# --- Disc ------------------------------------------------------------------------


def paint_disc(c: Canvas, frame: Page, kind: LabelKind, ctx: AlbumContext) -> None:
    box = _bleed_box(kind)
    if ctx.cover:
        _art(c, frame, ctx.cover, box, fx=ctx.style.disc_focus)
        return
    spec = LABELS[kind]
    _fill(c, frame, box, ctx.style.bg)
    f = fit(ctx.cased(ctx.album.title), ctx.style.title_font, spec.w - 2 * spec.safe_x, 12, 6)
    _text(c, frame, spec.w / 2, spec.h / 2, [(f.text, ctx.style.fg)], ctx.style.title_font, f.size, f.hscale, "center")


# --- Spines ----------------------------------------------------------------------


def paint_spine(c: Canvas, frame: Page, kind: LabelKind, ctx: AlbumContext) -> None:
    spec, s = LABELS[kind], ctx.style
    _fill(c, frame, _bleed_box(kind), s.bg)
    if ctx.album.spine_text:
        segments = [(ctx.cased(ctx.album.spine_text), s.fg)]
    else:
        segments = [(ctx.cased(ctx.album.artist), s.fg), (f"  {s.separator}  ", s.accent), (ctx.cased(ctx.album.title), s.fg)]
    text = "".join(t for t, _ in segments)
    f = fit(text, s.spine_font, spec.w - 2 * spec.safe_x, SPINE_MAX, SPINE_MIN)
    if f.shortened:
        ctx.warn(f"spine text too long even squeezed ({text!r}); set spine_text in album.json")
        segments = [(f.text, s.fg)]
    elif f.hscale < 1:
        ctx.warn(f"spine text squeezed to {f.hscale:.0%} width at {f.size:g} pt; consider spine_text")
    baseline = spec.h / 2 + cap_mm(s.spine_font, f.size) / 2
    _text(c, frame, spec.w / 2, baseline, segments, s.spine_font, f.size, f.hscale, "center")


# --- Slipcase front --------------------------------------------------------------


def paint_front(c: Canvas, frame: Page, kind: LabelKind, ctx: AlbumContext) -> None:
    spec, s = LABELS[kind], ctx.style
    box = _bleed_box(kind)
    _fill(c, frame, box, s.bg)
    if ctx.cover and s.front == "fill":
        _art(c, frame, ctx.cover, box, fy=s.front_focus)
        return
    if not ctx.cover:
        _panel_text(c, frame, ctx, Rect(spec.safe_x, spec.safe_y, spec.w - 2 * spec.safe_x, spec.h - 2 * spec.safe_y))
        return

    side = box.h  # the cover is square and fills the bleed box's height
    if s.front == "fit-left":
        art = Rect(box.x, box.y, side, side)
        panel = Rect(art.x1 + PANEL_ART_GAP, spec.safe_y, spec.w - spec.safe_x - art.x1 - PANEL_ART_GAP, spec.h - 2 * spec.safe_y)
    else:
        art = Rect(box.x1 - side, box.y, side, side)
        panel = Rect(spec.safe_x, spec.safe_y, art.x - PANEL_ART_GAP - spec.safe_x, spec.h - 2 * spec.safe_y)
    _art(c, frame, ctx.cover, art)
    _panel_text(c, frame, ctx, panel)


def _panel_text(c: Canvas, frame: Page, ctx: AlbumContext, panel: Rect) -> None:
    """Album title and artist/year beside the cover, reading bottom to top."""
    s = ctx.style
    title = ctx.cased(ctx.album.title)
    meta = " · ".join(filter(None, (ctx.album.artist, ctx.year)))
    # Lines run along the panel's height; their cap heights stack across its width.
    cap1, cap2 = cap_mm(s.title_font, 1), cap_mm(s.text_font, 1)
    f1 = fit(title, s.title_font, panel.h, min(PANEL_TITLE_MAX, 0.55 * panel.w / cap1), PANEL_TITLE_MIN)
    f2 = fit(meta, s.text_font, panel.h, min(PANEL_META_MAX, 0.25 * panel.w / cap2), PANEL_META_MIN)
    if f1.shortened or f2.shortened:
        ctx.warn("front panel text shortened; consider front: fill or a shorter title")
    gap = 0.4 * cap1 * f1.size
    block = cap1 * f1.size + gap + cap2 * f2.size + descent_mm(s.text_font, f2.size)
    x = panel.x + (panel.w - block) / 2
    base1 = x + cap1 * f1.size  # rotated glyphs' tops point left, so a line spans [base - cap, base]
    base2 = base1 + gap + cap2 * f2.size
    for base, f, font, color in ((base1, f1, s.title_font, s.fg), (base2, f2, s.text_font, s.accent)):
        length = width_mm(f.text, font, f.size, f.hscale)
        c.saveState()
        c.translate(*frame.pt(base, panel.y + (panel.h + length) / 2))
        c.rotate(90)
        draw(c, 0, 0, [(f.text, color)], font, f.size, f.hscale)
        c.restoreState()


# --- Slipcase back: track list ---------------------------------------------------


@dataclass
class _Row:
    number: str
    title: str
    duration: str
    heading: bool = False  # "DISC 2"


def _rows(ctx: AlbumContext) -> list[_Row]:
    s, tracks = ctx.style, ctx.album.tracks
    multi_disc = len({t.disc for t in tracks}) > 1
    rows, disc = [], None
    for t in tracks:
        if multi_disc and t.disc != disc:
            disc = t.disc
            rows.append(_Row("", f"DISC {disc}", "", heading=True))
        number = {"01": f"{t.number:02d}", "1": f"{t.number}.", "none": ""}[s.numbering]
        rows.append(_Row(number, t.title, fmt_duration(t.duration) if s.durations else ""))
    return rows


@dataclass
class _Layout:
    columns: int
    size: float
    hscale: float
    shortened: int  # titles that needed an ellipsis


def _plan(rows: list[_Row], font: str, area: Rect, columns: list[int]) -> _Layout | None:
    """Biggest type that fits every row; titles may squeeze, not shorten.

    Each extra column must buy at least COLUMN_COST pt of type size, so a list that nearly
    fits one column isn't split with a lone track in the second.
    """
    best = None
    for n in columns:
        col_w = (area.w - (n - 1) * COLUMN_GAP) / n
        size = TRACK_MAX
        while size >= TRACK_MIN - 1e-9:
            line = size * LINE_SPACING / mm_to_pt(1)
            per_col = int(area.h // line)
            if per_col * n >= len(rows):
                worst = min(_title_room(r, font, size, col_w) / max(width_mm(r.title, font, size), 1e-6) for r in rows)
                hscale = min(1.0, worst)
                if hscale >= 0.85:
                    cand = _Layout(n, size, hscale, 0)
                    if best is None or cand.size - COLUMN_COST * cand.columns > best.size - COLUMN_COST * best.columns:
                        best = cand
                    break
            size -= 0.25
    return best


def _title_room(r: _Row, font: str, size: float, col_w: float) -> float:
    num_w = width_mm("00", font, size) + 1.2
    dur_w = width_mm(r.duration, font, size) + 1.2 if r.duration else 0
    return col_w - num_w - dur_w


def paint_back(c: Canvas, frame: Page, kind: LabelKind, ctx: AlbumContext) -> None:
    spec, s = LABELS[kind], ctx.style
    _fill(c, frame, _bleed_box(kind), s.bg)
    x0, y0 = spec.safe_x, spec.safe_y
    w = spec.w - 2 * spec.safe_x

    # Header: album title, then artist · year · total time, then a rule.
    title = fit(ctx.cased(ctx.album.title), s.title_font, w, BACK_TITLE_MAX, BACK_TITLE_MIN)
    y = y0 + cap_mm(s.title_font, title.size)
    _text(c, frame, x0, y, [(title.text, s.fg)], s.title_font, title.size, title.hscale)
    total = sum(t.duration or 0 for t in ctx.album.tracks)
    meta_text = " · ".join(filter(None, (ctx.album.artist, ctx.year, fmt_duration(total) if s.durations else "")))
    meta = fit(meta_text, s.text_font, w, BACK_META, 4.5)
    y += 1.2 + cap_mm(s.text_font, meta.size)
    _text(c, frame, x0, y, [(meta.text, s.accent)], s.text_font, meta.size, meta.hscale)
    y += descent_mm(s.text_font, meta.size) + 0.8
    c.setStrokeColor(HexColor(s.accent))
    c.setLineWidth(0.4)
    c.line(*frame.pt(x0, y), *frame.pt(x0 + w, y))
    y += 1.2

    rows = _rows(ctx)
    if not rows:
        ctx.warn("no tracks to list on the slipcase back")
        return
    area = Rect(x0, y, w, spec.h - spec.safe_y - y)
    font = s.text_font
    layout = _plan(rows, font, area, [s.columns] if s.columns else [1, 2, 3])
    if layout is None:  # doesn't fit even squeezed: smallest type, most columns, shorten titles
        layout = _Layout(s.columns or 3, TRACK_MIN, 0.85, 0)
    line = layout.size * LINE_SPACING / mm_to_pt(1)
    room = max(1, int(area.h // line))
    per_col = min(room, -(-len(rows) // layout.columns))  # balance the columns
    col_w = (area.w - (layout.columns - 1) * COLUMN_GAP) / layout.columns
    dim = mix(s.fg, s.bg, 0.35)
    num_w = width_mm("00", font, layout.size) + 1.2
    if len(rows) > per_col * layout.columns:
        ctx.warn(f"track list doesn't fit: {len(rows)} rows, room for {per_col * layout.columns}")
    if layout.hscale < 0.95:
        ctx.warn(f"track titles squeezed to {layout.hscale:.0%} width at {layout.size:g} pt")

    for i, r in enumerate(rows[: per_col * layout.columns]):
        col, row = divmod(i, per_col)
        cx = area.x + col * (col_w + COLUMN_GAP)
        base = area.y + row * line + cap_mm(font, layout.size)
        if r.heading:
            _text(c, frame, cx, base, [(r.title, s.accent)], s.title_font, layout.size)
            continue
        room = _title_room(r, font, layout.size, col_w)
        title = ellipsize(r.title, font, layout.size, layout.hscale, room)
        if title.endswith(ELLIPSIS) and not r.title.endswith(ELLIPSIS):
            layout.shortened += 1
        if r.number:
            _text(c, frame, cx + num_w - 1.2, base, [(r.number, s.accent)], font, layout.size, align="right")
        _text(c, frame, cx + (num_w if r.number else 0), base, [(title, s.fg)], font, layout.size, layout.hscale)
        if r.duration:
            _text(c, frame, cx + col_w, base, [(r.duration, dim)], font, layout.size, align="right")
    if layout.shortened:
        ctx.warn(f"{layout.shortened} track title(s) shortened with an ellipsis")
    if layout.size < TRACK_MIN + 0.5:
        ctx.warn(f"track list set at {layout.size:g} pt (small); consider dropping durations or fewer columns")
