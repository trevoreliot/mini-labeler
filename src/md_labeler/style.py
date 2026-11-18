"""Per-album styling (work/<slug>/style.json), the art palette it's chosen from, and checks."""

from __future__ import annotations

import colorsys
import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from PIL import Image

FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
FRONT_LAYOUTS = ("fit-left", "fit-right", "fill")
NUMBERING = ("01", "1", "none")
MIN_CONTRAST_TEXT = 4.5  # WCAG AA
MIN_CONTRAST_ACCENT = 3.0


@dataclass
class Style:
    bg: str = "#111111"  # spines, slipcase back, and the panel beside the art on the front
    fg: str = "#f0f0f0"  # main text
    accent: str = "#d4a017"  # separators, track numbers, artist/year lines, rules
    spine_font: str = "BarlowCondensed-SemiBold"  # font names are TTF file stems in assets/fonts
    title_font: str = "BarlowCondensed-Bold"
    text_font: str = "IBMPlexSansCondensed-Regular"
    uppercase: bool = True  # spines and album titles
    separator: str = "·"  # between artist and album on the spines
    front: str = "fit-left"  # fit-left / fit-right: whole cover + title panel; fill: cover cropped to fill
    front_focus: float = 0.5  # fill: which part of the cover to keep vertically (0 top, 1 bottom)
    disc_focus: float = 0.5  # disc label: which part of the cover to keep horizontally (0 left, 1 right)
    numbering: str = "01"  # track numbers: "01", "1" or "none"
    durations: bool = True
    columns: int = 0  # track list columns; 0 = choose automatically (1–3)

    @classmethod
    def load(cls, path: Path) -> Style:
        data = json.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"{path}: unknown style keys {sorted(unknown)}")
        return cls(**data)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n")

    def problems(self) -> list[str]:
        """Invalid values, and text colours that are hard to read."""
        out = []
        fonts = available_fonts()
        for name in ("spine_font", "title_font", "text_font"):
            if getattr(self, name) not in fonts:
                out.append(f"{name} {getattr(self, name)!r} is not in assets/fonts")
        for name in ("bg", "fg", "accent"):
            if not HEX.match(getattr(self, name)):
                out.append(f"{name} {getattr(self, name)!r} is not a #rrggbb colour")
        if self.front not in FRONT_LAYOUTS:
            out.append(f"front must be one of {FRONT_LAYOUTS}")
        if self.numbering not in NUMBERING:
            out.append(f"numbering must be one of {NUMBERING}")
        if not 0 <= self.columns <= 3:
            out.append("columns must be 0 (auto) to 3")
        for name in ("front_focus", "disc_focus"):
            if not 0 <= getattr(self, name) <= 1:
                out.append(f"{name} must be between 0 and 1")
        if not out:
            if (r := contrast(self.fg, self.bg)) < MIN_CONTRAST_TEXT:
                out.append(f"fg/bg contrast {r:.1f}:1 is below {MIN_CONTRAST_TEXT}:1")
            if (r := contrast(self.accent, self.bg)) < MIN_CONTRAST_ACCENT:
                out.append(f"accent/bg contrast {r:.1f}:1 is below {MIN_CONTRAST_ACCENT}:1")
        return out


def available_fonts() -> dict[str, Path]:
    return {p.stem: p for p in sorted(FONTS_DIR.rglob("*.ttf"))}


# --- Colour ----------------------------------------------------------------------


def rgb(hex_: str) -> tuple[int, int, int]:
    return int(hex_[1:3], 16), int(hex_[3:5], 16), int(hex_[5:7], 16)


def to_hex(c: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, round(v))) for v in c))


def luminance(hex_: str) -> float:
    def lin(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (lin(v) for v in rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def mix(a: str, b: str, t: float) -> str:
    """`a` moved a fraction `t` toward `b`."""
    return to_hex(tuple(x + (y - x) * t for x, y in zip(rgb(a), rgb(b))))


# --- Palette ---------------------------------------------------------------------


def extract_palette(image: Image.Image, n: int = 6) -> dict:
    """Dominant colours of a cover (with their share of the image) and its average edge colour."""
    small = image.convert("RGB").resize((96, 96))
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors(), reverse=True)
    colors = [{"hex": to_hex(tuple(pal[i * 3 : i * 3 + 3])), "share": round(c / (96 * 96), 3)} for c, i in counts]
    w, h = small.size
    edge = [small.getpixel((x, y)) for x in range(w) for y in (0, h - 1)] + [small.getpixel((x, y)) for y in range(h) for x in (0, w - 1)]
    return {"colors": colors, "edge": to_hex(tuple(sum(c[i] for c in edge) / len(edge) for i in range(3)))}


def default_style(palette: dict | None) -> Style:
    """A readable starting style from the cover's palette, used until curation writes style.json."""
    if not palette:
        return Style()
    bg = palette["edge"]  # blends with the cover's border on the front panel
    fg = max(("#f4f4f4", "#141414"), key=lambda c: contrast(c, bg))
    light = fg == "#f4f4f4"
    if contrast(fg, bg) < MIN_CONTRAST_TEXT:  # mid-tone background: use pure white/black...
        fg = "#ffffff" if light else "#000000"
    while contrast(fg, bg) < MIN_CONTRAST_TEXT:  # ...and if that's not enough, push the background away
        bg = mix(bg, "#000000" if light else "#ffffff", 0.1)

    def vividness(hex_: str) -> float:
        _, l, s = colorsys.rgb_to_hls(*(v / 255 for v in rgb(hex_)))
        return s * (1 - abs(l - 0.5))

    accents = [c["hex"] for c in palette["colors"] if contrast(c["hex"], bg) >= MIN_CONTRAST_ACCENT]
    fallback = mix(fg, bg, 0.3)
    accent = max(accents, key=vividness) if accents else fallback if contrast(fallback, bg) >= MIN_CONTRAST_ACCENT else fg
    return Style(bg=bg, fg=fg, accent=accent)


def ensure_palette(work_dir: Path, art_file: str | None) -> dict | None:
    """work_dir/palette.json, extracted from the cover if it doesn't exist yet."""
    path = work_dir / "palette.json"
    if path.exists():
        return json.loads(path.read_text())
    if not art_file or not (work_dir / art_file).exists():
        return None
    with Image.open(work_dir / art_file) as img:
        palette = extract_palette(img)
    path.write_text(json.dumps(palette, indent=2) + "\n")
    return palette
