"""Packs labels onto sheets of blank sticker paper for hand cutting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from md_labeler.geometry import ALBUM_LABELS, LABELS, PAPER_SIZES, LabelKind, LabelSpec, Paper, Rect

EPS = 1e-6


@dataclass(frozen=True)
class SheetConfig:
    paper: Paper = Paper.LETTER
    margin: float = 6.0  # printer-safe margin on every page edge
    gutter: float = 3.0  # clear space between neighbouring bleed boxes (crop marks go here)
    footer: float = 12.0  # band at the bottom reserved for the ruler and print note

    @property
    def page_size(self) -> tuple[float, float]:
        return PAPER_SIZES[self.paper]

    @property
    def content_area(self) -> Rect:
        w, h = self.page_size
        return Rect(self.margin, self.margin, w - 2 * self.margin, h - 2 * self.margin - self.footer)

    @property
    def footer_area(self) -> Rect:
        w, h = self.page_size
        return Rect(self.margin, h - self.margin - self.footer, w - 2 * self.margin, self.footer)


@dataclass(frozen=True)
class LabelRequest:
    kind: LabelKind
    album: int  # index into the run's album list


@dataclass(frozen=True)
class Placement:
    page: int
    kind: LabelKind
    album: int
    x: float  # top-left of the cut box as it sits on the page, mm
    y: float
    rotated: bool = False  # turned 90° clockwise: the label's top edge faces the page's right edge

    @property
    def spec(self) -> LabelSpec:
        return LABELS[self.kind]

    @property
    def cut(self) -> Rect:
        """The cut box in page orientation (width and height swap when rotated)."""
        w, h = (self.spec.h, self.spec.w) if self.rotated else (self.spec.w, self.spec.h)
        return Rect(self.x, self.y, w, h)

    @property
    def bleed(self) -> Rect:
        return self.cut.outset(self.spec.bleed)


def album_requests(n_albums: int, kinds: tuple[LabelKind, ...] = ALBUM_LABELS) -> list[LabelRequest]:
    return [LabelRequest(k, a) for a in range(n_albums) for k in kinds]


def pack(requests: list[LabelRequest], cfg: SheetConfig) -> list[Placement]:
    """Pack labels onto as few pages as possible.

    Labels may be rotated 90°, because they are cut out by hand and orientation on the
    sheet doesn't matter. Runs MaxRects with a few sort orders and placement rules, and
    keeps the result with the fewest pages (then the emptiest last page).
    """
    best: list[Placement] | None = None
    for sort_key in _SORT_KEYS:
        for score in _SCORES:
            result = _maxrects(sorted(requests, key=sort_key), cfg, score)
            if best is None or _cost(result, cfg) < _cost(best, cfg):
                best = result
    return best or []


def capacity(cfg: SheetConfig, pages: int, kinds: tuple[LabelKind, ...] = ALBUM_LABELS) -> int:
    """The most albums whose full label sets fit on `pages` pages."""
    n = 0
    while _pages(pack(album_requests(n + 1, kinds), cfg)) <= pages:
        n += 1
    return n


# --- MaxRects ----------------------------------------------------------------
# Each label's footprint is its bleed box plus one gutter on the right and bottom. The
# bin is the content area plus one gutter, so the last label in a row or column needs
# no trailing gutter.


def _footprint(spec: LabelSpec, rotated: bool, gutter: float) -> tuple[float, float]:
    w, h = spec.w + 2 * spec.bleed + gutter, spec.h + 2 * spec.bleed + gutter
    return (h, w) if rotated else (w, h)


_SORT_KEYS: list[Callable[[LabelRequest], tuple]] = [
    lambda r: (-LABELS[r.kind].w * LABELS[r.kind].h,),  # largest area first
    lambda r: (-max(LABELS[r.kind].w, LABELS[r.kind].h),),  # longest side first
    lambda r: (-min(LABELS[r.kind].w, LABELS[r.kind].h),),  # widest short side first
]

# Lower is better. Arguments: free rect (w, h), item (w, h), free rect (x, y).
_Score = Callable[[float, float, float, float, float, float], tuple]
_SCORES: list[_Score] = [
    lambda fw, fh, w, h, x, y: (min(fw - w, fh - h), max(fw - w, fh - h)),  # best short side fit
    lambda fw, fh, w, h, x, y: (fw * fh - w * h, min(fw - w, fh - h)),  # best area fit
    lambda fw, fh, w, h, x, y: (y + h, x),  # bottom-left
]


class _Bin:
    def __init__(self, area: Rect, gutter: float):
        self.free = [Rect(area.x, area.y, area.w + gutter, area.h + gutter)]

    def find(self, w: float, h: float, score: _Score) -> tuple[tuple, Rect] | None:
        best = None
        for f in self.free:
            if w <= f.w + EPS and h <= f.h + EPS:
                s = score(f.w, f.h, w, h, f.x, f.y)
                if best is None or s < best[0]:
                    best = (s, Rect(f.x, f.y, w, h))
        return best

    def place(self, r: Rect) -> None:
        free: list[Rect] = []
        for f in self.free:
            free.extend(_split(f, r) if f.intersects(r) else [f])
        self.free = [f for i, f in enumerate(free) if not any(i != j and g.contains(f) and (g != f or j < i) for j, g in enumerate(free))]


def _split(f: Rect, r: Rect) -> list[Rect]:
    parts = []
    if r.x > f.x + EPS:
        parts.append(Rect(f.x, f.y, r.x - f.x, f.h))
    if r.x1 < f.x1 - EPS:
        parts.append(Rect(r.x1, f.y, f.x1 - r.x1, f.h))
    if r.y > f.y + EPS:
        parts.append(Rect(f.x, f.y, f.w, r.y - f.y))
    if r.y1 < f.y1 - EPS:
        parts.append(Rect(f.x, r.y1, f.w, f.y1 - r.y1))
    return parts


def _maxrects(requests: list[LabelRequest], cfg: SheetConfig, score: _Score) -> list[Placement]:
    area = cfg.content_area
    bins: list[_Bin] = []
    placements: list[Placement] = []

    for req in requests:
        spec = LABELS[req.kind]
        page = 0
        while True:
            fresh = page == len(bins)
            if fresh:
                bins.append(_Bin(area, cfg.gutter))
            choices = [
                (found, rot)
                for rot in (False, True)
                if (found := bins[page].find(*_footprint(spec, rot, cfg.gutter), score))
            ]
            if choices:
                (_, r), rot = min(choices, key=lambda c: c[0][0])
                break
            if fresh:
                raise ValueError(f"{req.kind} label does not fit on {cfg.paper} with these margins")
            page += 1
        bins[page].place(r)
        placements.append(Placement(page, req.kind, req.album, r.x + spec.bleed, r.y + spec.bleed, rot))

    return placements


def _pages(placements: list[Placement]) -> int:
    return max((p.page for p in placements), default=-1) + 1


def _cost(placements: list[Placement], cfg: SheetConfig) -> tuple[int, float]:
    last = _pages(placements) - 1
    used = sum(p.bleed.w * p.bleed.h for p in placements if p.page == last)
    return last + 1, used
