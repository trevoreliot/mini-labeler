import os

import pytest
from typer.testing import CliRunner

from md_labeler.cli import app
from md_labeler.geometry import Paper
from md_labeler.layout import SheetConfig, album_requests, pack
from md_labeler.printing import find_pdfs, lp_command, pdf_info
from md_labeler.render.sheet import render_pdf


def _sheet(path, paper):
    cfg = SheetConfig(paper=paper)
    return render_pdf(pack(album_requests(1), cfg), cfg, path)


@pytest.mark.parametrize("paper", list(Paper))
def test_pdf_info_detects_paper(tmp_path, paper):
    info = pdf_info(_sheet(tmp_path / "s.pdf", paper))
    assert info.paper is paper
    assert info.pages == 1


def test_lp_command_disables_scaling_and_sets_media(tmp_path):
    cmd = lp_command(tmp_path / "-odd name.pdf", Paper.A4, printer="P", copies=3)
    assert cmd[:3] == ["lp", "-d", "P"]
    assert "print-scaling=none" in cmd
    assert "fit-to-page=false" in cmd
    assert "media=A4" in cmd
    assert cmd[cmd.index("-n") + 1] == "3"
    assert cmd[-2:] == ["--", str(tmp_path / "-odd name.pdf")]  # file names starting with '-' are safe


def test_find_pdfs_newest_first(tmp_path):
    old = _sheet(tmp_path / "old.pdf", Paper.LETTER)
    new = _sheet(tmp_path / "run" / "new.pdf", Paper.A4)
    os.utime(old, (1_000_000, 1_000_000))
    assert [i.path for i in find_pdfs(tmp_path)] == [new, old]


def test_print_dry_run_reads_paper_from_pdf(tmp_path):
    pdf = _sheet(tmp_path / "s.pdf", Paper.A4)
    result = CliRunner().invoke(app, ["print", str(pdf), "--printer", "P", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "media=A4" in result.output
    assert "print-scaling=none" in result.output


def test_gray_adds_monochrome_options(tmp_path):
    color = lp_command(tmp_path / "s.pdf", Paper.LETTER)
    gray = lp_command(tmp_path / "s.pdf", Paper.LETTER, gray=True)
    assert "print-color-mode=monochrome" not in color
    assert {"print-color-mode=monochrome", "ColorModel=Gray"} <= set(gray)
    assert "print-scaling=none" in gray and gray[-2:] == color[-2:]  # still true size, same file
