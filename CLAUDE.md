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

### Printing (verified on the user's Canon G600, CUPS)
CUPS defaults to `print-scaling=auto`, which shrinks a full-size page to the printable area
by about 3%, even with "Actual size" selected in Okular. `mdl print` (in `printing.py`) runs
`lp -o media=<paper> -o print-scaling=none -o fit-to-page=false`, reading the paper size from
the PDF itself. With this, the 100 mm ruler measures true and no scale correction is needed. Don't add a
calibration factor to fix scaling problems; check the print path first.

## Tech stack
Python ≥3.12, managed with **uv** (`uv run`, `uv add`). Chosen libraries:
- **reportlab**: PDF generation (clip paths, embedded TTF fonts, precise placement).
- **Pillow**: art crop and resample.
- **musicbrainzngs** or plain `httpx`: MusicBrainz API.
- **pymupdf**: renders PNG proofs from the output PDF, and inspects templates.
- A palette extractor (for example `colorthief` or k-means in Pillow) feeds the styling step.
- CLI with `typer`. Tests with `pytest`.
- **mutagen** reads audio tags and embedded art. **pyside6-essentials** (Qt) for the album
  picker; uv's bundled Tk has no font rendering, so don't use tkinter.

Fonts are open-licence (OFL) TTFs committed under `assets/fonts/`, so output never depends on
system fonts. The styling step may only choose fonts that exist in that directory.

## Pipeline
Each stage reads and writes files under `work/<album-slug>/`, so stages can run again on
their own and Claude can edit the files between stages.

1. **Input**: a plain text file, one album per line: `Artist - Album`, optionally followed by a
   **tab** and the local album folder (`albumlist.py`). Blank lines and lines starting with `#`
   are ignored. Split on the **first** ` - ` (space-hyphen-space); album titles can themselves
   contain hyphens. Usually written by **`mdl pick`**: a Qt (PySide6) window over the user's library
   (`config.MUSIC_ROOT` = `/mnt/ssd500/Media/Music`, laid out `<artist>/<album>/<tracks>`).
   The user adds albums until the 2-page batch is full (8 Letter / 9 A4); the artist is the
   album folder's parent. The list goes to `selections/<date-time>.txt`, then fetch runs.
2. **Fetch, local first** (`fetch/local.py`): for entries with a folder, read tags with
   **mutagen** (album artist, album, year, track/disc numbers, titles, durations; WMA via ASF)
   and take the best cover: folder images named cover/front/folder first, then embedded
   front-cover pictures, then the highest resolution. Fall back to folder and file names for
   missing tags. Writes `album.json` and `cover.<ext>` (original bytes, not re-encoded).
   Anything local files can't supply goes in `Album.needs`: `"tracks"` (no tags or no
   folder) or `"art"` (no art, or under `geometry.art_px_needed()` = 851 px, which is 72 mm at
   300 dpi). An existing `album.json` is kept unless `--force`, so curated edits survive.
   Library survey (Nov 2026): 530 albums; 78% have embedded art (only about 45% of those are
   ≥851 px); 98% have full title tags; there are no folder images.
3. **Fetch, online** (`fetch/online.py`), only for albums whose `needs` contains `"art"`:
   - Find the MusicBrainz **release group**: search, then rank candidates by title similarity
     (against the tag title and the title with edition notes like "(Japanese Limited Edition)"
     stripped; MB `disambiguation` counts as part of the title, e.g. Weezer "Teal Album"), then
     Album over Single/EP, then no secondary types (Live/Compilation/Remix). The tag year only
     breaks ties, since tags often carry a reissue's year. Remaining ties → `needs_review: true`
     plus `candidates`; no art is downloaded. **To resolve: set `release_group` in album.json and
     re-run fetch** (a pinned group skips the search). Records `release_group` and
     `original_year` (use it over the tag year for display).
   - Art: Cover Art Archive front image at 1200 px, else **iTunes Search** (artwork URL
     `100x100bb` → `1200x1200bb`, matched on artist/album similarity). Replaces local art only
     if larger; the local original is kept as `cover-local.*`. **During curation, compare
     `cover-local.*` with `cover.*`** to catch wrong matches or off-colour scans, and swap back
     if the local one is better.
   - `fetch/http.py`: every response (and 404) is cached under `cache/`; `--refresh` ignores
     the cache. Per-host spacing (MusicBrainz 1.1 s, iTunes 3 s) and retries on 503/429,
     which MusicBrainz returns transiently under load. Always use `config.USER_AGENT`, which
     carries the user's email (`config.CONTACT`); MusicBrainz bans anonymous or over-fast
     clients.
   - Not built yet: track lists from MusicBrainz for albums with `"tracks"` in `needs`
     (typed-in entries with no folder, or untagged files).
   - Results on the first real batch (8 albums): 6 low-res covers were upgraded to
     1189–1425 px (5 from CAA, 1 from iTunes), and all 6 matches were correct.
4. **Curate** (Claude Code does this. **No LLM API calls in the code.**): see below.
5. **Render** (`mdl render [LIST]`, `render/run.py` + `render/labels.py`): for the newest
   (or given) album list, reads each `work/<slug>/` (`album.json`, `cover.*`, `style.json`) and
   writes `out/<list name>/labels.pdf` + `labels-proof-N.png`. Paper comes from the list's
   `# paper:` line (written by `mdl pick`). Albums without `style.json` get
   `style.default_style(palette)`, a readable style from the cover's colours. It prints
   warnings per album (squeezed/shortened text, small track list, low-res art, contrast,
   needs_review); **fix them in curation, not by changing code.**
   - Disc: cover cropped to fill the bleed box (`disc_focus` picks the horizontal crop).
   - Slipcase front: `fit-left`/`fit-right` puts the whole square cover (52 mm) on one side and
     the title and artist · year in a rotated panel on the other; `fill` crops the cover to
     70×50 (`front_focus` picks the vertical crop).
   - Slipcase back: title, artist · year · total time, a rule, then the track list. Type size
     ranges 7–4.5 pt across 1–3 balanced columns; an extra column must gain ≥1 pt. Titles squeeze
     to 85% before being shortened with "…". Multi-disc albums get "DISC n" headings.
   - Spines: "ARTIST · ALBUM" (separator in the accent colour), or `spine_text`; 7.5–5 pt, then
     squeezed to 80%, then shortened (with a warning).
   - Art is cropped and resampled to exactly 300 dpi and embedded as JPEG (q92, 4:4:4). The
     first batch's PDF was 2.1 MB.
6. **Proof**: Claude views the PNG proofs and checks for overflow, low contrast, bad crops,
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

**Styling** (write `style.json`; fields and checks in `style.Style`, `Style.problems()`):
```json
{"bg": "#111111", "fg": "#f0f0f0", "accent": "#d4a017",
 "spine_font": "BarlowCondensed-SemiBold", "title_font": "BarlowCondensed-Bold",
 "text_font": "IBMPlexSansCondensed-Regular", "uppercase": true, "separator": "·",
 "front": "fit-left", "front_focus": 0.5, "disc_focus": 0.5,
 "numbering": "01", "durations": true, "columns": 0}
```
Fonts are TTF file stems under `assets/fonts/`. Bundled (OFL, from google/fonts):
BarlowCondensed (Regular/Medium/SemiBold/Bold/ExtraBold), IBMPlexSansCondensed (Regular/Italic/
Medium/SemiBold/Bold), BebasNeue-Regular (caps only), CrimsonText (Regular/Italic/SemiBold/Bold),
SpaceMono (Regular/Bold). Use static TTFs only: reportlab can't use variable fonts' axes.
`palette.json` (written by fetch, or by render if missing) lists dominant colours with their
share of the cover, plus the average `edge` colour, which blends well as the front panel `bg`.
- Use `palette.json`, the cover art itself (Claude can view `cover.jpg`), and genre/era
  context to choose: the spine background and text colours, the font family and weight (only
  from `assets/fonts/`), case (upper/title), the separator glyph, and the track-list layout
  (columns, numbering style, durations on or off, accent colour).
- Maintain readable contrast (WCAG ≥4.5:1 for text). Tiny spine text needs it most.
- Keep it coherent with the album's visual identity, like a real CD back tray.

## Commands
```
uv run mdl testsheet [--paper letter|a4] [--pages 2 | --albums N]  # placeholder labels + guides -> out/testsheet.pdf
uv run mdl print [FILE] [--gui] [--dry-run]  # true-size print; no FILE = fzf picker over out/*.pdf
uv run mdl pick [--paper a4] [--music-root DIR] [--no-fetch]  # album picker window -> selections/*.txt -> fetch
uv run mdl fetch LIST [--force] [--offline] [--refresh]  # local tags/art, then CAA/iTunes for missing/low-res art
uv run mdl render [LIST] [--paper] [--guides]  # labels -> out/<list>/labels.pdf + proofs
uv run pytest
```

## Repo layout
```
assets/templates/   reference PDFs (read-only)
assets/fonts/       bundled OFL fonts (one folder per family, with OFL.txt)
src/md_labeler/
  geometry.py       all mm dimensions, label specs, outline paths
  layout.py         SheetConfig, packing labels onto pages
  render/sheet.py   PDF drawing; `LabelPainter` callback draws each label's content
  render/proof.py   PNG proofs via pymupdf
  render/labels.py  painters for disc, front, back, spines (AlbumContext collects warnings)
  render/text.py    font registration, fit (shrink → squeeze → ellipsis), drawing runs
  render/art.py     crop + resample cover to 300 dpi JPEG
  render/run.py     render stage: work dirs -> PDF + proofs
  style.py          Style (style.json), palette, contrast, default style
  printing.py       lp command, PDF paper detection, fzf / kdialog file pickers
  config.py         contact / User-Agent, printer, music root
  cli.py            typer app (`mdl`)
  models.py         Album / Track (album.json), slugify
  albumlist.py      read/write the album list file
  picker.py         Qt album picker window (pyside6-essentials)
  fetch/__init__.py fetch stage: album list -> work/<slug>/
  fetch/local.py    tags + cover art from local files (mutagen, Pillow)
  fetch/online.py   MusicBrainz release-group matching, Cover Art Archive, iTunes
  fetch/http.py     cached, rate-limited HTTP (httpx)
selections/         album lists written by `mdl pick` (gitignored)
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
