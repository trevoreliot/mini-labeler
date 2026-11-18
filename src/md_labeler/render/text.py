"""Measuring, fitting and drawing single lines of text, in mm."""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from md_labeler.geometry import MM_PER_PT
from md_labeler.style import available_fonts

MIN_HSCALE = 0.8  # narrowest horizontal squeeze before text is shortened with an ellipsis
ELLIPSIS = "…"

_registered: set[str] = set()


def register_fonts() -> None:
    for name, path in available_fonts().items():
        if name not in _registered:
            pdfmetrics.registerFont(TTFont(name, str(path)))
            _registered.add(name)


def width_mm(text: str, font: str, size: float, hscale: float = 1.0) -> float:
    return pdfmetrics.stringWidth(text, font, size) * hscale * MM_PER_PT


def cap_mm(font: str, size: float) -> float:
    return pdfmetrics.getFont(font).face.capHeight / 1000 * size * MM_PER_PT


def descent_mm(font: str, size: float) -> float:
    return -pdfmetrics.getFont(font).face.descent / 1000 * size * MM_PER_PT


@dataclass(frozen=True)
class Fit:
    text: str
    size: float  # pt
    hscale: float  # 1.0 = normal width
    shortened: bool  # an ellipsis replaced the end of the text


def fit(text: str, font: str, max_w: float, max_pt: float, min_pt: float) -> Fit:
    """Largest size ≤ max_pt that fits max_w mm; below min_pt, squeeze, then shorten."""
    w1 = width_mm(text, font, 1.0)
    if w1 == 0:
        return Fit(text, max_pt, 1.0, False)
    size = min(max_pt, max_w / w1)
    if size >= min_pt:
        return Fit(text, size, 1.0, False)
    hscale = max_w / (w1 * min_pt)
    if hscale >= MIN_HSCALE:
        return Fit(text, min_pt, hscale, False)
    return Fit(ellipsize(text, font, min_pt, MIN_HSCALE, max_w), min_pt, MIN_HSCALE, True)


def ellipsize(text: str, font: str, size: float, hscale: float, max_w: float) -> str:
    if width_mm(text, font, size, hscale) <= max_w + 1e-6:  # a squeeze computed to fit exactly must fit
        return text
    while text and width_mm(text.rstrip() + ELLIPSIS, font, size, hscale) > max_w:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


def draw(c: Canvas, x_pt: float, y_pt: float, segments: list[tuple[str, str]], font: str, size: float, hscale: float = 1.0) -> None:
    """Draw (text, #rrggbb) runs left to right from a baseline origin, in current canvas units."""
    t = c.beginText()
    t.setTextOrigin(x_pt, y_pt)
    t.setFont(font, size)
    t.setHorizScale(hscale * 100)
    for text, color in segments:
        t.setFillColor(HexColor(color))
        t.textOut(text)
    c.drawText(t)


def fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return ""
    s = round(seconds)
    h, rem = divmod(s, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{s // 60}:{s % 60:02d}"
