"""Cover art cropped and resampled to exactly its printed size at ART_DPI."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from md_labeler.geometry import ART_DPI

JPEG_QUALITY = 92


def art_jpeg(path: Path, w_mm: float, h_mm: float, focus_x: float = 0.5, focus_y: float = 0.5) -> bytes:
    """Crop the cover to w:h (keeping the focus point's side) and resample to ART_DPI.

    Returned as JPEG so the PDF embeds it as-is instead of re-encoding raw pixels.
    """
    tw, th = round(w_mm / 25.4 * ART_DPI), round(h_mm / 25.4 * ART_DPI)
    with Image.open(path) as src:
        img = src.convert("RGB")
    sw, sh = img.size
    if sw / sh > tw / th:  # source is wider: crop the sides
        cw = sh * tw / th
        x0 = (sw - cw) * focus_x
        box = (x0, 0, x0 + cw, sh)
    else:  # crop top and bottom
        ch = sw * th / tw
        y0 = (sh - ch) * focus_y
        box = (0, y0, sw, y0 + ch)
    out = io.BytesIO()
    img.resize((tw, th), Image.Resampling.LANCZOS, box=box).save(out, "JPEG", quality=JPEG_QUALITY, subsampling=0)
    return out.getvalue()
