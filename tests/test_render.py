"""Reads the rendered PDF back and checks physical sizes, independent of our own math."""

import pymupdf
import pytest

from md_labeler.geometry import LABELS, Paper, pt_to_mm
from md_labeler.layout import SheetConfig, album_requests, pack
from md_labeler.render.sheet import RULER_MM, render_pdf

TOL = 0.05  # mm


@pytest.mark.parametrize("paper", list(Paper))
def test_rendered_sizes_match_spec(tmp_path, paper):
    cfg = SheetConfig(paper=paper)
    placements = pack(album_requests(8), cfg)
    assert any(p.rotated for p in placements)
    pdf = render_pdf(placements, cfg, tmp_path / "t.pdf", show_guides=True)

    with pymupdf.open(pdf) as doc:
        w, h = cfg.page_size
        assert pt_to_mm(doc[0].rect.width) == pytest.approx(w, abs=TOL)
        assert pt_to_mm(doc[0].rect.height) == pytest.approx(h, abs=TOL)

        for i, page in enumerate(doc):
            # Cut outlines are the black unfilled shapes drawn by show_guides; crop marks
            # and ruler ticks are also black but are straight lines with no area.
            cuts = [
                d["rect"]
                for d in page.get_drawings()
                if d.get("color") == (0.0, 0.0, 0.0) and d.get("fill") is None and min(d["rect"].width, d["rect"].height) > 1
            ]
            expected = [p for p in placements if p.page == i]
            for pl in expected:
                match = [
                    r
                    for r in cuts
                    if abs(pt_to_mm(r.x0) - pl.x) < TOL and abs(pt_to_mm(r.y0) - pl.y) < TOL
                ]
                assert match, f"no cut outline found for {pl}"
                r = match[0]
                assert pt_to_mm(r.width) == pytest.approx(pl.cut.w, abs=TOL)
                assert pt_to_mm(r.height) == pytest.approx(pl.cut.h, abs=TOL)
                assert sorted((pl.cut.w, pl.cut.h)) == sorted((LABELS[pl.kind].w, LABELS[pl.kind].h))


def test_ruler_is_100mm(tmp_path):
    cfg = SheetConfig()
    pdf = render_pdf(pack(album_requests(1), cfg), cfg, tmp_path / "t.pdf")
    with pymupdf.open(pdf) as doc:
        lines = [
            it
            for d in doc[0].get_drawings()
            for it in d["items"]
            if it[0] == "l" and abs(it[1].y - it[2].y) < 1e-3
        ]
        longest = max(abs(it[2].x - it[1].x) for it in lines)
        assert pt_to_mm(longest) == pytest.approx(RULER_MM, abs=TOL)
