import math

import pytest

from md_labeler.geometry import DISC_CHAMFER, LABELS, LabelKind, disc_path


def _points(ops):
    pts = []
    for op in ops:
        if op[0] in ("M", "L"):
            pts.append(op[1:])
        elif op[0] == "C":
            pts.append(op[5:7])
    return pts


@pytest.mark.parametrize("offset", [0.0, 1.0, -0.5])
def test_disc_path_bbox(offset):
    spec = LABELS[LabelKind.DISC]
    xs, ys = zip(*_points(disc_path(10, 20, offset)))
    assert min(xs) == pytest.approx(10 - offset)
    assert min(ys) == pytest.approx(20 - offset)
    assert max(xs) == pytest.approx(10 + spec.w + offset)
    assert max(ys) == pytest.approx(20 + spec.h + offset)


def test_disc_chamfers_on_top_left_and_bottom_right():
    spec = LABELS[LabelKind.DISC]
    ops = disc_path(0, 0)
    assert ops[0] == ("M", DISC_CHAMFER, 0)  # top-left chamfer starts on the top edge
    assert ops[-2] == ("L", 0, DISC_CHAMFER)  # ...and ends on the left edge
    assert ops[3] == ("L", spec.w, spec.h - DISC_CHAMFER)
    assert ops[4] == ("L", spec.w - DISC_CHAMFER, spec.h)


@pytest.mark.parametrize("offset", [1.0, -0.5])
def test_offset_chamfer_is_parallel_and_at_distance(offset):
    # The chamfer line x + y = c moves to x + y = c - offset·√2 (outward is toward the corner).
    ox, oy = disc_path(0, 0, offset)[0][1:]
    assert ox + oy == pytest.approx(DISC_CHAMFER - offset * math.sqrt(2))
