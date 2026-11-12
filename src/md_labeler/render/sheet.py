"""Draws packed labels onto PDF pages at exact physical size."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from reportlab.lib.colors import Color, black, magenta
from reportlab.pdfgen.canvas import Canvas

from md_labeler.geometry import PathOp, label_path, mm_to_pt, safe_rect
from md_labeler.layout import Placement, SheetConfig

HAIRLINE = 0.25  # pt
CROP_OFFSET = 0.5  # mm gap between bleed edge and crop mark

LIGHT_CYAN = Color(0.6, 1.0, 1.0)
BLEED_FILL = Color(0.9, 0.97, 1.0)
GREY = Color(0.55, 0.55, 0.55)

# Draws a label's content in the label's own frame: the cut box spans (0, 0)–(spec.w, spec.h)
# mm with y down, whatever the label's position or rotation on the sheet. The canvas is
# already clipped to the bleed path.
LabelPainter = Callable[[Canvas, "Page", Placement], None]


class Page:
    """Wraps a canvas so callers work in mm with y pointing down.

    `h` is the height of the frame: the page height for the sheet, the label height for a
    label frame.
    """

    def __init__(self, canvas: Canvas, height_mm: float):
        self.c = canvas
        self.h = height_mm

    def pt(self, x: float, y: float) -> tuple[float, float]:
        return mm_to_pt(x), mm_to_pt(self.h - y)

    def path(self, ops: list[PathOp]):
        p = self.c.beginPath()
        for op in ops:
            match op:
                case ("M", x, y):
                    p.moveTo(*self.pt(x, y))
                case ("L", x, y):
                    p.lineTo(*self.pt(x, y))
                case ("C", x1, y1, x2, y2, x3, y3):
                    p.curveTo(*self.pt(x1, y1), *self.pt(x2, y2), *self.pt(x3, y3))
                case ("Z",):
                    p.close()
        return p

    def line(self, x0: float, y0: float, x1: float, y1: float) -> None:
        self.c.line(*self.pt(x0, y0), *self.pt(x1, y1))


def render_pdf(
    placements: list[Placement],
    cfg: SheetConfig,
    out: Path,
    painter: LabelPainter | None = None,
    show_guides: bool = False,
) -> Path:
    """Write every page to `out`. With `show_guides`, also draw cut and safe outlines."""
    w, h = cfg.page_size
    out.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(out), pagesize=(mm_to_pt(w), mm_to_pt(h)))
    c.setTitle("md-labeler sheet")
    page = Page(c, h)
    n_pages = max((p.page for p in placements), default=0) + 1

    for i in range(n_pages):
        for pl in (p for p in placements if p.page == i):
            _draw_label(page, pl, painter or placeholder_painter, show_guides)
            _crop_marks(page, pl, cfg.gutter)
        _footer(page, cfg, i, n_pages)
        c.showPage()

    c.save()
    return out


def _draw_label(page: Page, pl: Placement, painter: LabelPainter, show_guides: bool) -> None:
    c, spec = page.c, pl.spec
    c.saveState()
    # Move the origin to the label frame's bottom-left corner. A rotated label is turned
    # 90° clockwise, so that corner sits at the cut box's top-left on the page.
    if pl.rotated:
        c.translate(*page.pt(pl.x, pl.y))
        c.rotate(-90)
    else:
        c.translate(*page.pt(pl.x, pl.y + spec.h))
    frame = Page(c, spec.h)

    c.saveState()
    c.clipPath(frame.path(label_path(spec, 0, 0, spec.bleed)), stroke=0, fill=0)
    painter(c, frame, pl)
    c.restoreState()

    if show_guides:
        c.setLineWidth(HAIRLINE)
        c.setStrokeColor(LIGHT_CYAN)
        c.drawPath(frame.path(label_path(spec, 0, 0, spec.bleed)), stroke=1, fill=0)
        c.setStrokeColor(black)
        c.drawPath(frame.path(label_path(spec, 0, 0)), stroke=1, fill=0)
        s = safe_rect(spec, 0, 0)
        c.setStrokeColor(magenta)
        c.setDash(1, 1)
        c.rect(*frame.pt(s.x, s.y1), mm_to_pt(s.w), mm_to_pt(s.h), stroke=1, fill=0)
    c.restoreState()


def placeholder_painter(c: Canvas, frame: Page, pl: Placement) -> None:
    """Test-sheet content: a pale fill to show the bleed, plus the label's name and size."""
    spec = pl.spec
    b = spec.bleed
    c.setFillColor(BLEED_FILL)
    c.rect(*frame.pt(-b, spec.h + b), mm_to_pt(spec.w + 2 * b), mm_to_pt(spec.h + 2 * b), stroke=0, fill=1)
    size = 5 if spec.h < 10 else 7
    c.setFillColor(GREY)
    c.setFont("Helvetica", size)
    cx, cy = spec.w / 2, spec.h / 2
    text = f"{spec.kind}  #{pl.album + 1}  {spec.w:g}×{spec.h:g} mm"
    c.drawCentredString(*frame.pt(cx, cy + size * 0.35 * 25.4 / 72), text)


def _crop_marks(page: Page, pl: Placement, gutter: float) -> None:
    """Short marks in the gutter, in line with each edge of the cut box."""
    b, cut = pl.spec.bleed, pl.cut
    start = b + CROP_OFFSET
    length = max((gutter - 2 * CROP_OFFSET) / 2, 0.5)
    c = page.c
    c.saveState()
    c.setLineWidth(HAIRLINE)
    c.setStrokeColor(black)
    for x in (cut.x, cut.x1):
        page.line(x, cut.y - start, x, cut.y - start - length)
        page.line(x, cut.y1 + start, x, cut.y1 + start + length)
    for y in (cut.y, cut.y1):
        page.line(cut.x - start, y, cut.x - start - length, y)
        page.line(cut.x1 + start, y, cut.x1 + start + length, y)
    c.restoreState()


RULER_MM = 100


def _footer(page: Page, cfg: SheetConfig, index: int, n_pages: int) -> None:
    """A 100 mm ruler for checking print scale, and the print-settings reminder."""
    f = cfg.footer_area
    c = page.c
    c.saveState()
    c.setLineWidth(HAIRLINE)
    c.setStrokeColor(black)
    base = f.y + 3.5
    page.line(f.x, base, f.x + RULER_MM, base)
    for i in range(RULER_MM + 1):
        tick = 2.5 if i % 10 == 0 else 1.5 if i % 5 == 0 else 0.8
        page.line(f.x + i, base, f.x + i, base + tick)
    c.setFont("Helvetica", 5)
    c.setFillColor(black)
    for i in range(0, RULER_MM + 1, 10):
        c.drawCentredString(*page.pt(f.x + i, base + 4.6), str(i // 10))
    c.drawString(*page.pt(f.x + RULER_MM + 3, base + 1.5), f"← must measure exactly {RULER_MM} mm")
    c.setFont("Helvetica", 6)
    c.setFillColor(GREY)
    note = f'Print at 100% / Actual size, disable "Fit to Page" • {cfg.paper.value} • page {index + 1} of {n_pages}'
    c.drawString(*page.pt(f.x, f.y1 - 1), note)
    c.restoreState()
