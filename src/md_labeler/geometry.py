"""Every physical dimension in the project, in millimetres.

Coordinates are in mm with the origin at the top-left and y increasing downward,
matching how the labels are measured. The renderer converts to PDF points and
flips y; nothing else should.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

MM_PER_PT = 25.4 / 72


def mm_to_pt(v: float) -> float:
    return v / MM_PER_PT


def pt_to_mm(v: float) -> float:
    return v * MM_PER_PT


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def x1(self) -> float:
        return self.x + self.w

    @property
    def y1(self) -> float:
        return self.y + self.h

    def outset(self, d: float) -> Rect:
        return Rect(self.x - d, self.y - d, self.w + 2 * d, self.h + 2 * d)

    def intersects(self, o: Rect) -> bool:
        return self.x < o.x1 and o.x < self.x1 and self.y < o.y1 and o.y < self.y1

    def contains(self, o: Rect) -> bool:
        return self.x <= o.x and self.y <= o.y and o.x1 <= self.x1 and o.y1 <= self.y1


# --- Paper -----------------------------------------------------------------


class Paper(StrEnum):
    LETTER = "letter"
    A4 = "a4"


PAPER_SIZES: dict[Paper, tuple[float, float]] = {
    Paper.LETTER: (215.9, 279.4),
    Paper.A4: (210.0, 297.0),
}

# --- Labels ----------------------------------------------------------------


class LabelKind(StrEnum):
    DISC = "disc"
    DISC_SPINE = "disc_spine"
    CASE_FRONT = "case_front"
    CASE_BACK = "case_back"
    CASE_SPINE = "case_spine"


class Shape(StrEnum):
    RECT = "rect"
    DISC = "disc"  # chamfered top-left/bottom-right, rounded top-right/bottom-left


@dataclass(frozen=True)
class LabelSpec:
    kind: LabelKind
    w: float  # cut size
    h: float
    bleed: float  # art extends this far past the cut line on every side
    safe_x: float  # text/important content stays this far inside the cut line
    safe_y: float
    shape: Shape = Shape.RECT


# Disc label outline, measured from assets/templates/MiniDisc Labels Layout Template.pdf
DISC_CHAMFER = 2.12  # leg length of the 45° chamfers
DISC_RADIUS = 1.0  # radius of the two rounded corners

LABELS: dict[LabelKind, LabelSpec] = {
    LabelKind.DISC: LabelSpec(LabelKind.DISC, 37.0, 54.0, 1.0, 0.9, 1.35, Shape.DISC),
    LabelKind.DISC_SPINE: LabelSpec(LabelKind.DISC_SPINE, 58.5, 3.5, 1.0, 1.5, 0.3),
    LabelKind.CASE_FRONT: LabelSpec(LabelKind.CASE_FRONT, 70.0, 50.0, 1.0, 2.0, 2.0),
    LabelKind.CASE_BACK: LabelSpec(LabelKind.CASE_BACK, 70.0, 50.0, 1.0, 2.0, 2.0),
    LabelKind.CASE_SPINE: LabelSpec(LabelKind.CASE_SPINE, 60.0, 3.5, 1.0, 1.5, 0.3),
}

# Labels printed for each album, in the order they are grouped on the sheet.
ALBUM_LABELS: tuple[LabelKind, ...] = (
    LabelKind.DISC,
    LabelKind.CASE_FRONT,
    LabelKind.CASE_BACK,
    LabelKind.DISC_SPINE,
    LabelKind.CASE_SPINE,
)

# --- Outline paths -----------------------------------------------------------
# A path is a list of ops in mm: ("M", x, y), ("L", x, y),
# ("C", x1, y1, x2, y2, x3, y3) and ("Z",).

PathOp = tuple

_KAPPA = 4 * (math.sqrt(2) - 1) / 3  # cubic Bézier approximation of a quarter circle


def rect_path(r: Rect) -> list[PathOp]:
    return [("M", r.x, r.y), ("L", r.x1, r.y), ("L", r.x1, r.y1), ("L", r.x, r.y1), ("Z",)]


def disc_path(x: float, y: float, offset: float = 0.0) -> list[PathOp]:
    """Disc label outline with its cut box at (x, y), grown outward by `offset`.

    A positive offset gives the bleed path, a negative one the safe area. Offsetting a
    45° chamfer by d moves its legs by d·(2 − √2); rounded corners grow by d.
    """
    spec = LABELS[LabelKind.DISC]
    d = offset
    x0, y0 = x - d, y - d
    x1, y1 = x + spec.w + d, y + spec.h + d
    c = DISC_CHAMFER + d * (2 - math.sqrt(2))
    r = max(DISC_RADIUS + d, 0.0)
    k = r * _KAPPA
    return [
        ("M", x0 + c, y0),
        ("L", x1 - r, y0),
        ("C", x1 - r + k, y0, x1, y0 + r - k, x1, y0 + r),  # top-right, rounded
        ("L", x1, y1 - c),
        ("L", x1 - c, y1),  # bottom-right, chamfered
        ("L", x0 + r, y1),
        ("C", x0 + r - k, y1, x0, y1 - r + k, x0, y1 - r),  # bottom-left, rounded
        ("L", x0, y0 + c),
        ("Z",),  # closes the top-left chamfer
    ]


def label_path(spec: LabelSpec, x: float, y: float, offset: float = 0.0) -> list[PathOp]:
    if spec.shape is Shape.DISC:
        return disc_path(x, y, offset)
    return rect_path(Rect(x, y, spec.w, spec.h).outset(offset))


def safe_rect(spec: LabelSpec, x: float, y: float) -> Rect:
    return Rect(x + spec.safe_x, y + spec.safe_y, spec.w - 2 * spec.safe_x, spec.h - 2 * spec.safe_y)


# --- Raster art ----------------------------------------------------------------

ART_DPI = 300


def art_px_needed() -> int:
    """Pixels needed on the cover's short side to print every art label at ART_DPI.

    The cover is square, so it must cover the longest bleed-box side of any label it fills.
    """
    longest = max(max(LABELS[k].w, LABELS[k].h) + 2 * LABELS[k].bleed for k in (LabelKind.DISC, LabelKind.CASE_FRONT))
    return math.ceil(longest / 25.4 * ART_DPI)
