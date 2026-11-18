"""The album list file: the pipeline's input.

One album per line, `Artist - Album`, optionally followed by a tab and the album's local
folder. Blank lines and lines starting with `#` are ignored. The line splits on the first
` - `, since album titles can contain hyphens.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AlbumEntry:
    artist: str
    album: str
    folder: Path | None = None

    def line(self) -> str:
        text = f"{self.artist} - {self.album}"
        return f"{text}\t{self.folder}" if self.folder else text


def read_album_list(path: Path) -> list[AlbumEntry]:
    entries = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        text, _, folder = raw.partition("\t")
        artist, sep, album = text.partition(" - ")
        if not sep or not artist.strip() or not album.strip():
            raise ValueError(f"{path}:{n}: expected 'Artist - Album', got {raw!r}")
        entries.append(AlbumEntry(artist.strip(), album.strip(), Path(folder.strip()) if folder.strip() else None))
    return entries


def write_album_list(path: Path, entries: list[AlbumEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(e.line() + "\n" for e in entries))
