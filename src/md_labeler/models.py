"""Album data shared by the pipeline stages, round-tripped through work/<slug>/album.json."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class Track:
    number: int
    title: str
    duration: float | None = None  # seconds
    disc: int = 1


@dataclass
class Album:
    artist: str
    title: str
    year: str | None = None
    tracks: list[Track] = field(default_factory=list)
    folder: str | None = None  # local album folder the data came from
    mbid: str | None = None  # MusicBrainz release ID, once known
    release_group: str | None = None  # MusicBrainz release group ID; set it by hand to pin a match
    original_year: str | None = None  # first release year per MusicBrainz (tags often carry a reissue's)
    art_file: str | None = None  # cover image file name inside the album's work dir
    art_source: str | None = None  # "folder:<name>", "embedded:<track file>", "caa:<release group>", "itunes:<id>"
    art_px: int | None = None  # short side of the cover image, in pixels
    needs: list[str] = field(default_factory=list)  # what local files couldn't supply: "art", "tracks"
    spine_text: str | None = None  # curated override for the spines
    needs_review: bool = False  # MusicBrainz match was ambiguous; see `candidates`
    candidates: list[str] = field(default_factory=list)  # "Artist - Title (year, type) [release group id]"

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> Album:
        data = json.loads(path.read_text())
        data["tracks"] = [Track(**t) for t in data.get("tracks", [])]
        return cls(**data)


def slugify(*parts: str) -> str:
    text = unicodedata.normalize("NFKD", " ".join(parts)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "album"
