# md-labeler

Print-ready MiniDisc labels from your music library. Pick albums in a window, and md-labeler
gathers their track lists and cover art (from your own files first, then online). After
curation it lays everything out at exact physical size on sticker paper, as a PDF you print
at 100% and cut by hand.

Each album gets five labels:

| Label          | Cut size (mm)      | Content                                                      |
|----------------|--------------------|--------------------------------------------------------------|
| Disc           | 37 × 54, chamfered | Cover art cropped to the disc label shape                    |
| Disc spine     | 58.5 × 3.5         | ARTIST · ALBUM                                               |
| Slipcase front | 70 × 50            | Cover art with a title panel, or the cover filling the label |
| Slipcase back  | 70 × 50            | Track list, like the back of a CD case                       |
| Slipcase spine | 60 × 3.5           | ARTIST · ALBUM                                               |

Two pages hold a full batch: **8 albums on US Letter, 9 on A4**.

## Requirements

- Linux with a CUPS printer
- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 and all dependencies)
- Optional: `fzf` for the terminal file picker in `mdl print`; `kdialog` or `zenity` for
  `mdl print --gui`

## Setup

```sh
git clone <this repo> && cd md-labeler
uv sync
```

Then set these environment variables, for example in your shell profile:

```sh
export MD_LABELER_CONTACT="https://github.com/<you>"   # or your email
export MD_LABELER_MUSIC_ROOT="$HOME/Music"
export MD_LABELER_PRINTER="My_Printer"                 # optional
```

| Variable                 | What it's for                                                                                         |
|--------------------------|-------------------------------------------------------------------------------------------------------|
| `MD_LABELER_CONTACT`     | Your email or URL. MusicBrainz requires contact info in every request and blocks anonymous clients. **Set this to your own.** |
| `MD_LABELER_MUSIC_ROOT`  | Your library, laid out as `<root>/<artist>/<album>/<tracks>`. `~` is expanded.                        |
| `MD_LABELER_PRINTER`     | CUPS printer name. If unset, the system default (`lpstat -d`) is used.                                |

Unset or empty variables fall back to the defaults in `src/md_labeler/config.py`, which are
the author's own settings.

### Check your printer's scaling first

```sh
uv run mdl testsheet                 # placeholder labels with cut/safe guides -> out/testsheet.pdf
uv run mdl print out/testsheet.pdf
```

Measure the 100 mm ruler at the bottom of the page. If it comes out short, the print system
is shrinking the page. Use `mdl print`, never a viewer's print dialog (see
[Printing](#printing)).

## Workflow

```sh
uv run mdl pick       # 1. choose albums; fetch runs automatically afterwards
                      # 2. curate: ask Claude Code to curate the batch
uv run mdl render     # 3. draw the labels -> out/<batch>/labels.pdf + PNG proofs
uv run mdl print      # 4. pick the PDF and print at true size
```

1. **Pick.** Expand an artist and double-click albums (or select one and click **Add →**)
   until the slots are full; the search box filters artists and albums. Each row shows what
   your files provide, e.g. `10 tracks, art 1000px`. **Make labels** saves the list to
   `selections/<date-time>.txt` and fetches each album into `work/<album>/`.
2. **Curate.** Rendering works without this step, using automatic colours from each cover.
   Curation cleans titles (edition notes like "(Deluxe Edition)", "(Bonus Track)"), picks the
   right MusicBrainz match when it was ambiguous, chooses art crops, and writes a `style.json`
   per album (colours, fonts, layout). This repo is set up for [Claude Code](https://claude.com/claude-code)
   to do it: ask it to "curate the batch". The rules it follows are in `CLAUDE.md`. You can
   also edit the files by hand (see [Work folder](#work-folder)).
3. **Render.** Writes `labels.pdf` and a PNG preview per page, and lists warnings per album,
   such as text that had to be squeezed or shortened, low-res art, or poor contrast. Fix those
   in curation and render again.
4. **Print**, then cut along the crop marks.

You can also skip the picker and write an album list yourself (see [Album list](#album-list)),
then run `uv run mdl fetch mylist.txt`.

## Commands

All commands run as `uv run mdl <command>`. Add `--help` to any command for its options.

### `mdl pick`

Opens the album picker window. When you click **Make labels**, it writes the album list and
runs `fetch`.

| Option                       | Default                            | Description                                               |
|------------------------------|------------------------------------|-----------------------------------------------------------|
| `--music-root DIR`           | `$MD_LABELER_MUSIC_ROOT`           | Library to browse (`<root>/<artist>/<album>`). Can also be changed in the window. |
| `--paper letter\|a4`         | `letter`                           | Sets the number of slots (8 / 9). Can also be changed in the window. |
| `--out FILE`                 | `selections/<date-time>.txt`       | Where to write the album list.                            |
| `--fetch` / `--no-fetch`     | `--fetch`                          | Run the fetch stage afterwards.                           |
| `--offline` / `--no-offline` | `--no-offline`                     | Fetch from local files only, without online lookups.      |

### `mdl fetch LIST`

Gathers metadata and cover art for every album in an album list into `work/<album>/`.

- **Local files first.** Tags give the artist, album, year, track and disc numbers, titles
  and durations (MP3, FLAC, M4A, OGG, WMA and more). Cover art comes from image files in the
  album folder or art embedded in the tracks, whichever is the best front cover.
- **Online only for gaps.** The album is matched on MusicBrainz, and then:
  - **Track list**, when there are no local files (a typed-in entry) or their tags have no
    titles: taken from one edition of the album. It prefers an official release, the edition
    named in your title (e.g. "Remain in Light - Deluxe") or otherwise the standard one, a
    track count matching your files, CD over digital over vinyl, and then the earliest date.
  - **Cover art**, when there's none or it's under 851 px (too soft for a 72 mm label at
    300 dpi): downloaded from the Cover Art Archive, falling back to iTunes. Your art is only
    replaced by a larger image, and your original is kept as `cover-local.*`.
  - If several albums match equally well (e.g. Weezer's many albums titled "Weezer"), nothing
    is downloaded; the album is marked for review with a list of candidates.
- Albums that already have an `album.json` are kept as they are, so curated edits survive
  re-runs. Online lookups for their missing art still run.

| Option                       | Default        | Description                                                         |
|------------------------------|----------------|---------------------------------------------------------------------|
| `LIST`                       | (required)     | Album list file.                                                    |
| `--force` / `--no-force`     | `--no-force`   | Re-read albums that already have an `album.json`. **Discards curated edits.** |
| `--offline` / `--no-offline` | `--no-offline` | Local files only.                                                   |
| `--refresh` / `--no-refresh` | `--no-refresh` | Ignore cached HTTP responses in `cache/` and ask again.             |

### `mdl render [LIST]`

Lays out and draws every label for the albums in a list, from their `work/` folders.

| Option                     | Default                                  | Description                                                        |
|----------------------------|------------------------------------------|--------------------------------------------------------------------|
| `LIST`                     | newest file in `selections/`             | Album list to render. Every album must have been fetched.          |
| `--paper letter\|a4`       | the list's `# paper:` line, else letter  | Paper size.                                                        |
| `--guides` / `--no-guides` | `--no-guides`                            | Also draw cut, bleed and safe-area outlines, for checking only.    |
| `--out FILE`               | `out/<list name>/labels.pdf`             | PDF to write. PNG proofs go next to it.                            |

### `mdl print [PDF]`

Prints a sheet at true size. The paper size (Letter or A4) is read from the PDF itself.

| Option            | Default                                 | Description                                                         |
|-------------------|-----------------------------------------|---------------------------------------------------------------------|
| `PDF`             | (opens a picker)                        | PDF to print. Without it, a searchable `fzf` list of `out/**/*.pdf` opens, newest first (or a numbered list if `fzf` isn't installed). |
| `--gui`           | off                                     | Pick the file in a desktop dialog (`kdialog`, else `zenity`).       |
| `--printer NAME`  | `$MD_LABELER_PRINTER`, else system default | CUPS printer.                                                       |
| `--copies N`      | `1`                                     | Number of copies.                                                   |
| `--dry-run`       | off                                     | Show the `lp` command without printing.                             |

### `mdl testsheet`

Placeholder labels with cut, bleed and safe-area guides, for checking sizes and scaling on
your printer.

| Option               | Default              | Description                                    |
|----------------------|----------------------|------------------------------------------------|
| `--paper letter\|a4` | `letter`             | Paper size.                                    |
| `--pages N`          | `2`                  | Fill this many pages with as many albums as fit. |
| `--albums N`         | (from `--pages`)     | Lay out exactly this many albums instead.      |
| `--out FILE`         | `out/testsheet.pdf`  | PDF to write.                                  |

## Album list

Plain text, one album per line:

```text
# paper: letter
AC DC - Back in Black	/mnt/music/AC DC/Back in Black
Talking Heads - Remain in Light - Deluxe
```

- `Artist - Album`, split on the **first** ` - `, so album titles can contain hyphens.
- Optionally a **tab** and the album's folder; without one, the album is looked up online only.
- Blank lines and `#` comments are ignored. `# paper: letter|a4` records the batch's paper size
  for `mdl render`. `mdl pick` writes it for you.

## Work folder

`work/<artist-album>/` holds everything for one album. The stages read and write these files,
so you can edit them between stages.

| File            | Written by     | Contents                                                                 |
|-----------------|----------------|--------------------------------------------------------------------------|
| `album.json`    | fetch, curation | Artist, title, year, tracks; where the art came from; what's still missing |
| `cover.*`       | fetch          | The cover art used for printing                                          |
| `cover-local.*` | fetch          | Your original art, kept when an online image replaced it                 |
| `palette.json`  | fetch / render | The cover's dominant colours and average edge colour                     |
| `style.json`    | curation       | How the labels look (below). Without it, a default from the palette is used. |

Useful `album.json` fields to edit:

| Field           | Effect                                                                                   |
|-----------------|------------------------------------------------------------------------------------------|
| `title`, `artist`, `tracks[].title` | What's printed. Clean up edition notes and typos here.                    |
| `spine_text`    | Replaces "ARTIST · ALBUM" on both spines, when the default is too long or redundant.        |
| `release_group` | Pins the MusicBrainz match. When `needs_review` is true, pick an ID from `candidates`, set it here, and run `fetch` again. |
| `tracks_source` | `local`, or `musicbrainz:<release id>` when the track list came from MusicBrainz. |
| `original_year` | First release year per MusicBrainz. It's printed instead of `year`, since tags often carry a reissue's year. |

### `style.json`

```json
{
  "bg": "#151315", "fg": "#e8e4dc", "accent": "#c9a45c",
  "spine_font": "CrimsonText-SemiBold", "title_font": "CrimsonText-SemiBold",
  "text_font": "IBMPlexSansCondensed-Regular",
  "uppercase": false, "separator": "·",
  "front": "fit-left", "front_focus": 0.5, "disc_focus": 0.5,
  "numbering": "01", "durations": true, "columns": 0
}
```

| Key           | Values                                | Description                                                       |
|---------------|---------------------------------------|-------------------------------------------------------------------|
| `bg`          | `#rrggbb`                             | Background of the spines, the slipcase back and the front title panel. |
| `fg`          | `#rrggbb`                             | Main text. Needs at least 4.5:1 contrast with `bg`.               |
| `accent`      | `#rrggbb`                             | Separators, track numbers, artist/year lines and rules. Needs at least 3:1 contrast with `bg`. |
| `spine_font`, `title_font`, `text_font` | font name   | A TTF file name (without `.ttf`) from `assets/fonts/`. See [Fonts](#fonts). |
| `uppercase`   | `true` / `false`                      | Capitalise the spines and album titles.                           |
| `separator`   | text                                  | Between artist and album on the spines.                           |
| `front`       | `fit-left`, `fit-right`, `fill`       | `fit-*`: the whole cover plus a title panel on the other side. `fill`: the cover cropped to fill 70×50. |
| `front_focus` | 0–1                                   | With `fill`: which part of the cover to keep vertically (0 top, 1 bottom). |
| `disc_focus`  | 0–1                                   | Disc label: which part of the cover to keep horizontally (0 left, 1 right). The square cover loses 30% of its width. |
| `numbering`   | `"01"`, `"1"`, `"none"`               | Track number style.                                               |
| `durations`   | `true` / `false`                      | Show track durations and the total time. Turn off to make room for long titles. |
| `columns`     | `0`–`3`                               | Track list columns; `0` chooses automatically.                    |

## Printing

Always print with `mdl print`. Even with "Actual size" selected in a viewer like Okular,
CUPS's default `print-scaling=auto` shrinks a full-page PDF by about 3% to fit the printable
area. `mdl print` runs:

```sh
lp -d <printer> -o media=<Letter|A4> -o print-scaling=none -o fit-to-page=false -- labels.pdf
```

Every sheet has a 100 mm ruler in its footer to confirm the scale. Labels stay at least 6 mm
from the page edge, inside most printers' printable area. Make sure the loaded paper matches
the PDF's paper size.

Labels may be turned 90° on the sheet to fit more per page, and one album's labels can land
on different pages. Each label is cut out separately, so this doesn't matter.

## Fonts

Bundled in `assets/fonts/` under the SIL Open Font License (each family's `OFL.txt` is
included):

| Family                 | Styles                                    | Good for                       |
|------------------------|-------------------------------------------|--------------------------------|
| Barlow Condensed       | Regular, Medium, SemiBold, Bold, ExtraBold | Spines, titles                 |
| IBM Plex Sans Condensed | Regular, Italic, Medium, SemiBold, Bold  | Track lists (legible when small) |
| Bebas Neue             | Regular (capitals only)                   | Bold display titles            |
| Crimson Text           | Regular, Italic, SemiBold, Bold           | Serif titles and spines        |
| Space Mono             | Regular, Bold                             | Typewriter-style track lists (runs wide) |

To add a font, drop a **static** (not variable) `.ttf` into a folder under `assets/fonts/`
and use its file name in `style.json`.

## Troubleshooting

| Problem                                        | Fix                                                                                   |
|------------------------------------------------|---------------------------------------------------------------------------------------|
| Ruler measures under 100 mm                    | Print with `mdl print`, not a viewer. Check the PDF's paper size matches the loaded paper. |
| `still needs: review match`                    | Several MusicBrainz albums matched equally well. Set `release_group` in `album.json` from `candidates` and run `fetch` again. |
| Wrong or poor online cover                     | Compare `cover.*` with `cover-local.*`; to use your own, swap the files and update `art_file`/`art_px` in `album.json` (see `CLAUDE.md`). |
| `spine text too long` / `squeezed` warnings    | Set a shorter `spine_text` in `album.json`.                                            |
| Track list `squeezed` / `shortened` warnings   | In `style.json`, set `"durations": false`, or try `"columns": 2`; or shorten titles in `album.json`. |
| MusicBrainz errors (503)                       | Usually temporary. Requests are retried automatically; run `fetch` again later.       |
| Changed your music files                       | `mdl fetch LIST --force` re-reads them (and discards curated edits for those albums). |

## Development

```sh
uv run pytest
```

Design notes, label geometry, pipeline details and curation rules are in `CLAUDE.md`.

## License

md-labeler is free software, licensed under the
[GNU General Public License v3.0 or later](LICENSE) (`GPL-3.0-or-later`). This matches its
copyleft dependencies: [mutagen](https://github.com/quodlibet/mutagen) is GPL-2.0-or-later,
and [PyMuPDF](https://github.com/pymupdf/PyMuPDF) is AGPL-3.0. The other dependencies
(reportlab, Pillow, httpx, typer, PySide6) are under permissive or LGPL licenses.

The fonts in `assets/fonts/` are not covered by the GPL. They are under the
[SIL Open Font License 1.1](https://openfontlicense.org), with each family's license and
copyright notice in its `OFL.txt`. Keep those files with the fonts if you redistribute them.
The fonts may not be sold on their own.

## Disclaimers

- **No affiliation.** MiniDisc is a trademark of Sony Group Corporation. This project is not
  affiliated with or endorsed by Sony, the MetaBrainz Foundation (MusicBrainz), the Internet
  Archive or the Cover Art Archive, Apple (iTunes), or any artist or record label.
- **Album art and names belong to their owners.** Cover art, album and track titles, and band
  logos are copyrighted or trademarked by their respective owners. md-labeler is intended for
  making labels, for personal use, for recordings you own. Don't sell or distribute labels
  made with other people's artwork. This repository contains no cover art: fetched images stay
  in your local `work/` and `cache/` folders, which are not tracked in git.
- **Online services.** Track lists come from [MusicBrainz](https://musicbrainz.org), whose core
  data is released under CC0. Cover images from the Cover Art Archive and iTunes remain under
  their owners' copyright, and Apple's iTunes Search API is subject to Apple's terms. Set your
  own contact in `MD_LABELER_CONTACT` (see [Setup](#setup)); md-labeler limits requests to MusicBrainz's
  allowed rate and caches every response, so please don't remove those limits.
- **No warranty.** md-labeler is provided "as is", without warranty of any kind; see the
  [license](LICENSE) for the full terms. Print results depend on your printer, paper and
  settings. Print `mdl testsheet` and check its 100 mm ruler before using your good sticker
  paper.
