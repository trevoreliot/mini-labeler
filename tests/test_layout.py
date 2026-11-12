from collections import Counter
from itertools import combinations

import pytest

from md_labeler.geometry import ALBUM_LABELS, Paper
from md_labeler.layout import SheetConfig, album_requests, capacity, pack


@pytest.mark.parametrize("paper", list(Paper))
@pytest.mark.parametrize("n_albums", [1, 4, 13])
def test_pack_places_everything_without_overlap(paper, n_albums):
    cfg = SheetConfig(paper=paper)
    placements = pack(album_requests(n_albums), cfg)

    assert Counter(p.kind for p in placements) == {k: n_albums for k in ALBUM_LABELS}
    for p in placements:
        assert cfg.content_area.contains(p.bleed), p
    for a, b in combinations(placements, 2):
        if a.page == b.page:
            # Neighbouring bleed boxes keep a full gutter between them for crop marks.
            assert not a.bleed.outset(cfg.gutter / 2 - 1e-6).intersects(b.bleed.outset(cfg.gutter / 2 - 1e-6)), (a, b)


@pytest.mark.parametrize(("paper", "albums"), [(Paper.LETTER, 8), (Paper.A4, 9)])
def test_two_page_capacity(paper, albums):
    # Both are at the practical limit: one album's labels plus gutters take ~11,820 mm²,
    # and two pages hold ~107,000 mm² (Letter) or ~111,000 mm² (A4).
    assert capacity(SheetConfig(paper=paper), pages=2) == albums


def test_rotation_is_used_and_swaps_footprint():
    placements = pack(album_requests(8), SheetConfig(paper=Paper.LETTER))
    rotated = [p for p in placements if p.rotated]
    assert rotated
    for p in rotated:
        assert (p.cut.w, p.cut.h) == (p.spec.h, p.spec.w)


def test_label_too_big_for_page_raises():
    with pytest.raises(ValueError):
        pack(album_requests(1), SheetConfig(margin=100))
