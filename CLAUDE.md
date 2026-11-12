# md-labeler

Generates print-ready MiniDisc labels from a list of albums. For each album it fetches the
cover art and track list, styles the spine and track-list typography, lays everything out on
sticker paper at exact physical size, and writes a PDF to print at 100% scale. Personal hobby
project; the user runs it on Linux.

## Labels produced per album

| Label            | Cut size (mm)          | Content                                                        |
|------------------|------------------------|----------------------------------------------------------------|
| Disc label       | 37 × 54, chamfered     | Cover art only, resized/cropped to the shape. No text.         |
| Disc spine       | 58.5 × 3.5             | Artist / album, styled per album                               |
| Slipcase front   | 70 × 50                | Cover art (+ optional styling per album)                       |
| Slipcase back    | 70 × 50                | Track listing in the style of a CD back tray                   |
| Slipcase spine   | 60 × 3.5               | Artist / album, styled per album                               |

### Disc label shape (measured from the reference template)
37 × 54 mm. The **top-left and bottom-right** corners are chamfered at 45°, with legs of
**2.12 mm**. The top-right and bottom-left corners are rounded with a **1.0 mm radius**. The
safe margin is 0.9 mm horizontally and 1.35 mm vertically inside the cut line. The template's
bleed was uneven (0.95/1.35 mm); we use a uniform **1.0 mm**, so the bleed path is a true
offset of the cut path (`geometry.disc_path(offset=…)`). Art is clipped to the bleed path. The chamfer must be on the correct corners, because it keys to the
MiniDisc shell.

### Spines are tiny
3.5 mm tall is about 9.9 pt. Usable cap height is about 2.2 mm, so text is roughly 6–7 pt and
must be one line. Fit text by shrinking the size (with a minimum floor) and then condensing
the tracking. If it still does not fit, use the `spine_text` override (see Metadata cleanup)
instead of letting text overflow. Use condensed typefaces with good small-size legibility.

## Reference templates
`assets/templates/` holds the original layouts. They are **reference only, not production
layouts**:
- `MiniDisc Labels Layout Template.pdf`: US Letter, 5×4 disc labels and 18 spine strips.
  The geometry above came from here.
- `SlipCase Labels Layout Template.pdf`: A4, 70×50 cells and 60×3.5 spines. **Its grid is
  broken**: the column pitch is 60.8 mm but the cells are 70 mm wide, so they overlap.
  Use it only for the label dimensions.

The user prints on **blank sticker paper and cuts by hand**, so we own the sheet layout:
- Paper size is configurable. Support **US Letter and A4**, and keep the paper size in config,
  never hard-coded.
- Every label has 1 mm bleed. Bleed boxes are separated by a 3 mm gutter, and the crop marks
  for each label sit in that gutter (`SheetConfig` in `layout.py`). The page margin is 6 mm,
  and a 12 mm footer band holds the ruler.
- `layout.pack` runs MaxRects bin packing with several sort orders and placement rules, and
  keeps the result with the fewest pages. Labels may be **rotated 90°** (`Placement.rotated`),
  since they are hand-cut and orientation on the sheet doesn't matter. All label types share
  sheets, so one album's labels can end up on different pages.
- **Capacity: 8 albums per 2 Letter pages, 9 per 2 A4 pages** (`layout.capacity`). Both are at
  the practical limit: one album's labels plus gutters take ~11,820 mm², and two pages hold
  ~107,000 mm² (Letter) or ~111,000 mm² (A4). Shrinking the margin or gutter doesn't raise it.
- Painters draw in the label's own frame (cut box at (0,0)–(w,h) mm), so rotation is handled
  once, in `render.sheet._draw_label`.

## Print accuracy rules
- Output is a **vector PDF** with real-world units (points, 1 pt = 1/72 in). Shapes and text
  stay vector, fonts are embedded (subset), and raster art is embedded at **≥300 dpi
  effective** for its placed size.
  Resample art to exactly the placed size at 300 dpi (for example, 70 mm is about 827 px) so
  the PDF viewer does not resample it.
- Every dimension is defined in **mm** in one geometry module and converted at render time.
- Add a 100 mm **calibration ruler** in a sheet margin so the user can check the printer
  did not scale the page. Add footer text: "Print at 100% / Actual size, disable Fit to Page".
- Also write a **PNG proof** of each sheet (150 dpi) for quick visual review.
- Colour is RGB (home inkjet or laser printer). No CMYK pipeline.

## Tech stack
Python ≥3.12, managed with **uv** (`uv run`, `uv add`). Chosen libraries:
- **reportlab**: PDF generation (clip paths, embedded TTF fonts, precise placement).
- **Pillow**: art crop and resample.
- **musicbrainzngs** or plain `httpx`: MusicBrainz API.
- **pymupdf**: renders PNG proofs from the output PDF, and inspects templates.
- A palette extractor (for example `colorthief` or k-means in Pillow) feeds the styling step.
- CLI with `typer`. Tests with `pytest`.

Fonts are open-licence (OFL) TTFs committed under `assets/fonts/`, so output never depends on
system fonts. The styling step may only choose fonts that exist in that directory.

## Pipeline
Each stage reads and writes files under `work/<album-slug>/`, so stages can run again on
their own and Claude can edit the files between stages.

1. **Input**: a plain text file, one album per line: `Artist - Album`. Blank lines and lines
   starting with `#` are ignored. Split on the **first** ` - ` (space-hyphen-space); album
   titles can themselves contain hyphens.
2. **Fetch** (`mdl fetch albums.txt`): search MusicBrainz for the release group, then choose a
   release. Prefer the original CD issue, then vinyl, and avoid deluxe or remaster editions
   unless the user requested one. Writes `album.json` (artist, title, year, release MBID,
   tracks with numbers, titles and durations, plus disc/side breaks for multi-disc or vinyl
   releases) and `cover.jpg` from the **Cover Art Archive** (`front` image, largest size).
   Fallback for missing art: **iTunes Search API** (no key; change the `100x100bb` artwork
   URL to `3000x3000bb`). Also writes `palette.json`. Cache all HTTP responses under
   `cache/`.
   - MusicBrainz rules: **1 request/second maximum**, and a descriptive `User-Agent`
     including contact info. Use `config.USER_AGENT`, which carries the user's email
     (`config.CONTACT`). Breaking these gets the
     user IP-banned.
   - If the match is ambiguous or poor, still write `album.json` but add `"needs_review": true`
     and the candidate release IDs, rather than guessing silently.
3. **Curate** (Claude Code does this. **No LLM API calls in the code.**): see below.
4. **Render** (`mdl render`): reads `album.json`, `style.json` and `cover.jpg`, and writes
   `out/<run>/labels.pdf` and `out/<run>/proof-*.png`.
5. **Proof**: Claude views the PNG proofs and checks for overflow, low contrast, bad crops,
   and a chamfer on the wrong corner.

## Curate step (Claude's job)
Claude Code is the "LLM agent". The Python code is deterministic and makes no LLM calls.
After `fetch`, for every album without a `style.json` (or that has `needs_review`), Claude:

**Metadata cleanup** (edit `album.json`):
- Resolve `needs_review` by picking the correct release from the candidates, then fetch again
  pinned to that MBID if needed.
- Remove noise like "(Remastered 2011)", "- Single Version" or "[Explicit]" from track titles,
  unless it actually tells versions apart.
- Add `spine_text` when "Artist — Album" will not fit the spine legibly (abbreviate
  sensibly, never just truncate).
- If the track list will not fit the 70×50 back at a legible size (minimum about 5 pt), plan
  two columns, drop durations, or both, and record that in the style.

**Styling** (write `style.json`, validated by a schema in the code):
- Use `palette.json`, the cover art itself (Claude can view `cover.jpg`), and genre/era
  context to choose: the spine background and text colours, the font family and weight (only
  from `assets/fonts/`), case (upper/title), the separator glyph, and the track-list layout
  (columns, numbering style, durations on or off, accent colour).
- Maintain readable contrast (WCAG ≥4.5:1 for text). Tiny spine text needs it most.
- Keep it coherent with the album's visual identity, like a real CD back tray.

## Commands
```
uv run mdl testsheet [--paper letter|a4] [--pages 2 | --albums N]  # placeholder labels + guides -> out/testsheet.pdf
uv run pytest
# planned:
uv run mdl fetch albums.txt            # metadata + art -> work/
uv run mdl render [--paper letter|a4]  # PDF + PNG proofs -> out/
```

## Repo layout
```
assets/templates/   reference PDFs (read-only)
assets/fonts/       bundled OFL fonts (planned)
src/md_labeler/
  geometry.py       all mm dimensions, label specs, outline paths
  layout.py         SheetConfig, packing labels onto pages
  render/sheet.py   PDF drawing; `LabelPainter` callback draws each label's content
  render/proof.py   PNG proofs via pymupdf
  config.py         contact / User-Agent
  cli.py            typer app (`mdl`)
  fetch/, models.py (planned)
work/               per-album intermediate files (gitignored)
cache/              HTTP cache (gitignored)
out/                generated PDFs/proofs (gitignored)
tests/
```

## Conventions
- All physical dimensions are defined once, in mm, in `geometry.py`. No magic numbers in
  render code.
- The renderer works in mm with y pointing down (`render.sheet.Page`). Only `Page` converts
  to PDF points and flips y.
- Test the geometry: assert that rendered label rects (pymupdf can read them back from the
  PDF) match the spec to within 0.05 mm, and that labels never overlap or cross the
  printer-safe page margin (default 6 mm).
- Data models (album, track, style) are dataclasses or pydantic, round-tripped through JSON.
- Do not commit fetched cover art or generated output. They are copyrighted, for personal use.
