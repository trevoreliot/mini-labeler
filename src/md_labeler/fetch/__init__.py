"""The fetch stage: album list -> work/<slug>/album.json + cover image.

Local files are read first. Whatever they can't supply is recorded in `Album.needs`; then
missing track lists come from MusicBrainz, and missing or low-res art from the Cover Art
Archive or iTunes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from md_labeler.albumlist import AlbumEntry
from md_labeler.fetch.http import Http
from md_labeler.fetch.local import is_album_folder, read_album
from md_labeler.fetch.online import lookup_art, lookup_tracks
from md_labeler.geometry import art_px_needed
from md_labeler.models import Album, slugify
from md_labeler.style import ensure_palette

WORK_DIR = Path("work")


@dataclass
class FetchResult:
    entry: AlbumEntry
    dir: Path
    album: Album
    skipped: bool  # album.json already existed and was kept
    online: list[str] = field(default_factory=list)  # summaries of the online lookups that ran


def fetch_entry(entry: AlbumEntry, work_dir: Path = WORK_DIR, force: bool = False, http: Http | None = None) -> FetchResult:
    """Read local files into work/<slug>/, then fill gaps online if `http` is given."""
    result = _fetch_local(entry, work_dir, force)
    album = result.album
    if http and "tracks" in album.needs:
        result.online.append("tracks: " + lookup_tracks(album, http))
        album.save(result.dir / "album.json")
    if http and "art" in album.needs and not album.needs_review:
        art_before = album.art_file, album.art_source
        result.online.append("art: " + lookup_art(album, result.dir, http))
        album.save(result.dir / "album.json")
        if (album.art_file, album.art_source) != art_before:
            (result.dir / "palette.json").unlink(missing_ok=True)
    ensure_palette(result.dir, result.album.art_file)  # for choosing the style during curation
    return result


def _fetch_local(entry: AlbumEntry, work_dir: Path, force: bool) -> FetchResult:
    out = work_dir / slugify(entry.artist, entry.album)
    meta = out / "album.json"
    if meta.exists() and not force:  # keep curated edits
        return FetchResult(entry, out, Album.load(meta), skipped=True)

    out.mkdir(parents=True, exist_ok=True)
    if entry.folder and is_album_folder(entry.folder):
        album, cover = read_album(entry.folder, entry.artist, entry.album)
    else:
        album, cover = Album(artist=entry.artist, title=entry.album, needs=["tracks"]), None

    for old in (*out.glob("cover.*"), *out.glob("cover-local.*"), *out.glob("palette.json")):
        old.unlink()
    if cover:
        album.art_file = f"cover{cover.ext}"
        album.art_source, album.art_px = cover.source, cover.px
        (out / album.art_file).write_bytes(cover.data)
    if not cover or cover.px < art_px_needed():
        album.needs.append("art")

    album.save(meta)
    return FetchResult(entry, out, album, skipped=False)
