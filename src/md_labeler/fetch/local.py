"""Reads album metadata and cover art from a local album folder, to avoid API calls."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path

import mutagen
from mutagen.asf import ASF
from PIL import Image

from md_labeler.models import Album, Track

AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".wma", ".wav", ".aiff", ".ape", ".wv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
# Folder images whose names suggest the front cover, best first.
COVER_NAMES = ("cover", "front", "folder", "albumart", "album")
FRONT_COVER = 3  # ID3/FLAC picture type


def audio_files(folder: Path) -> list[Path]:
    return sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTS)


def is_album_folder(folder: Path) -> bool:
    try:
        return any(f.suffix.lower() in AUDIO_EXTS for f in folder.iterdir() if f.is_file())
    except OSError:
        return False


# --- Tags ----------------------------------------------------------------------


@dataclass
class _Tags:
    artist: str | None = None
    albumartist: str | None = None
    album: str | None = None
    date: str | None = None
    title: str | None = None
    track: int | None = None
    disc: int | None = None
    length: float | None = None


def _first(tags, *keys) -> str | None:
    for k in keys:
        v = tags.get(k) if tags is not None else None
        if v:
            v = v[0] if isinstance(v, list) else v
            text = str(v).strip()
            if text:
                return text
    return None


def _number(text: str | None) -> int | None:
    m = re.match(r"\s*(\d+)", text or "")  # "3/12" -> 3
    return int(m.group(1)) if m else None


def read_tags(path: Path) -> _Tags:
    try:
        f = mutagen.File(path, easy=True)
    except Exception:  # unreadable or corrupt file: fall back to the file name
        return _Tags()
    if f is None:
        return _Tags()
    length = getattr(f.info, "length", None)
    if isinstance(f, ASF):  # WMA has no "easy" interface
        t = f.tags
        return _Tags(
            artist=_first(t, "Author", "WM/AlbumArtist"),
            albumartist=_first(t, "WM/AlbumArtist"),
            album=_first(t, "WM/AlbumTitle"),
            date=_first(t, "WM/Year"),
            title=_first(t, "Title"),
            track=_number(_first(t, "WM/TrackNumber", "WM/Track")),
            disc=_number(_first(t, "WM/PartOfSet")),
            length=length,
        )
    t = f.tags
    return _Tags(
        artist=_first(t, "artist"),
        albumartist=_first(t, "albumartist"),
        album=_first(t, "album"),
        date=_first(t, "date", "originaldate", "year"),
        title=_first(t, "title"),
        track=_number(_first(t, "tracknumber")),
        disc=_number(_first(t, "discnumber")),
        length=length,
    )


def _title_from_filename(path: Path) -> str:
    # "03 - Hells Bells.mp3" / "03. Hells Bells.mp3" -> "Hells Bells"
    return re.sub(r"^\s*\d+\s*[-._)]?\s*", "", path.stem).strip() or path.stem


def _mode(values: list[str | None]) -> str | None:
    present = [v for v in values if v]
    return max(set(present), key=present.count) if present else None


# --- Art -----------------------------------------------------------------------


@dataclass
class Cover:
    data: bytes
    ext: str  # ".jpg" / ".png" / ...
    px: int  # short side
    source: str


def _cover(data: bytes, source: str) -> Cover | None:
    try:
        img = Image.open(io.BytesIO(data))
        fmt, size = img.format, img.size
    except Exception:
        return None
    ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif", "BMP": ".bmp"}.get(fmt or "", ".img")
    return Cover(data, ext, min(size), source)


def _embedded_pictures(path: Path) -> list[tuple[int, bytes]]:
    """(picture type, image bytes) for every picture embedded in an audio file."""
    try:
        f = mutagen.File(path)
    except Exception:
        return []
    if f is None:
        return []
    pics = []
    for p in getattr(f, "pictures", None) or []:  # FLAC
        pics.append((p.type, p.data))
    tags = f.tags
    if tags is None:
        return pics
    for key in list(tags.keys()):
        if key.startswith("APIC"):  # MP3 (ID3)
            pics.append((tags[key].type, tags[key].data))
    for cover in tags.get("covr", []) if hasattr(tags, "get") else []:  # MP4
        pics.append((FRONT_COVER, bytes(cover)))
    if isinstance(f, ASF):
        for v in tags.get("WM/Picture", []):
            pics.append(_asf_picture(v.value))
    return [p for p in pics if p[1]]


def _asf_picture(raw: bytes) -> tuple[int, bytes]:
    # WM/Picture: type (1 byte), size (4 bytes), MIME and description (UTF-16, NUL-terminated), data
    ptype, pos = raw[0], 5
    for _ in range(2):
        while raw[pos : pos + 2] != b"\x00\x00":
            pos += 2
        pos += 2
    return ptype, raw[pos:]


def find_cover(folder: Path, files: list[Path]) -> Cover | None:
    """The best cover: front covers beat other pictures, then the highest resolution wins."""
    candidates: list[tuple[bool, Cover]] = []
    for img in sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS):
        if c := _cover(img.read_bytes(), f"folder:{img.name}"):
            front = any(img.stem.lower().startswith(n) for n in COVER_NAMES)
            candidates.append((front, c))
    seen: set[int] = set()
    for f in files:
        for ptype, data in _embedded_pictures(f):
            if hash(data) in seen:  # usually the same image is embedded in every track
                continue
            seen.add(hash(data))
            if c := _cover(data, f"embedded:{f.name}"):
                candidates.append((ptype == FRONT_COVER, c))
    if not candidates:
        return None
    return max(candidates, key=lambda fc: (fc[0], fc[1].px))[1]


# --- Album ---------------------------------------------------------------------


def read_album(folder: Path, artist_hint: str, album_hint: str) -> tuple[Album, Cover | None]:
    """Build an Album from tags, falling back to the folder names for missing fields."""
    files = audio_files(folder)
    tags = [read_tags(f) for f in files]

    tracks = []
    for i, (f, t) in enumerate(zip(files, tags), 1):
        tracks.append(Track(number=t.track or i, title=t.title or _title_from_filename(f), duration=t.length, disc=t.disc or 1))
    tracks.sort(key=lambda t: (t.disc, t.number))

    album = Album(
        artist=_mode([t.albumartist for t in tags]) or _mode([t.artist for t in tags]) or artist_hint,
        title=_mode([t.album for t in tags]) or album_hint,
        year=(_mode([t.date for t in tags]) or "")[:4] or None,
        tracks=tracks,
        folder=str(folder),
    )
    if not tracks or not all(t.title for t in tags):
        album.needs.append("tracks")
    return album, find_cover(folder, files)
