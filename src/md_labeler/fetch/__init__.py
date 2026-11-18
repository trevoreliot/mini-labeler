"""The fetch stage: album list -> work/<slug>/album.json + cover image.

Local files are read first. Whatever they can't supply is recorded in `Album.needs`, for
MusicBrainz / Cover Art Archive to fill in (not built yet).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from md_labeler.albumlist import AlbumEntry
from md_labeler.fetch.local import is_album_folder, read_album
from md_labeler.geometry import art_px_needed
from md_labeler.models import Album, slugify

WORK_DIR = Path("work")


@dataclass
class FetchResult:
    entry: AlbumEntry
    dir: Path
    album: Album
    skipped: bool  # album.json already existed and was kept


def fetch_entry(entry: AlbumEntry, work_dir: Path = WORK_DIR, force: bool = False) -> FetchResult:
    out = work_dir / slugify(entry.artist, entry.album)
    meta = out / "album.json"
    if meta.exists() and not force:  # keep curated edits
        return FetchResult(entry, out, Album.load(meta), skipped=True)

    out.mkdir(parents=True, exist_ok=True)
    if entry.folder and is_album_folder(entry.folder):
        album, cover = read_album(entry.folder, entry.artist, entry.album)
    else:
        album, cover = Album(artist=entry.artist, title=entry.album, needs=["tracks"]), None

    for old in out.glob("cover.*"):
        old.unlink()
    if cover:
        album.art_file = f"cover{cover.ext}"
        album.art_source, album.art_px = cover.source, cover.px
        (out / album.art_file).write_bytes(cover.data)
    if not cover or cover.px < art_px_needed():
        album.needs.append("art")

    album.save(meta)
    return FetchResult(entry, out, album, skipped=False)
