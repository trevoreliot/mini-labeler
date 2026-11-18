"""Fills gaps left by local files: cover art from the Cover Art Archive, then iTunes.

The album is identified as a MusicBrainz release group (all editions of one album).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from md_labeler.fetch.http import Http, NotFound
from md_labeler.fetch.local import Cover, cover_from_bytes
from md_labeler.geometry import art_px_needed
from md_labeler.models import Album

MB_API = "https://musicbrainz.org/ws/2"
CAA_API = "https://coverartarchive.org"
ITUNES_API = "https://itunes.apple.com/search"
ART_SIZE = 1200  # px; CAA thumbnail size / iTunes artwork size to request
MATCH = 0.9  # minimum title/artist similarity (0–1) to accept a match

# Bracketed parts of a title that describe an edition rather than the album:
# "(2 Vinyl, LP)", "[Remastered 2011]", "(Japanese Limited Edition)". "(Teal Album)" stays.
EDITION = re.compile(
    r"\s*[(\[][^)\]]*\b(edition|deluxe|remaster(ed)?|vinyl|lp|bonus|expanded|anniversary|japan(ese)?"
    r"|limited|reissue|version|mono|stereo|disc|cd|explicit)\b[^)\]]*[)\]]",
    re.IGNORECASE,
)


def clean_title(title: str) -> str:
    return EDITION.sub("", title).strip() or title


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = re.sub(r"\s*&\s*", " and ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return re.sub(r"^the ", "", text)


def similar(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


# --- MusicBrainz -----------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    artist: str
    year: str | None
    primary_type: str | None
    secondary_types: tuple[str, ...]
    score: int  # MusicBrainz search score
    disambiguation: str = ""  # e.g. "Teal Album" for one of Weezer's many albums titled "Weezer"

    @property
    def names(self) -> tuple[str, ...]:
        return (self.title, f"{self.title} ({self.disambiguation})") if self.disambiguation else (self.title,)

    def describe(self) -> str:
        kind = "/".join(filter(None, (self.primary_type, *self.secondary_types)))
        return f"{self.artist} - {self.names[-1]} ({self.year or '?'}, {kind or '?'}) [{self.id}]"


def _lucene(text: str) -> str:
    return re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r"\\\1", text)


def search_release_groups(http: Http, artist: str, title: str) -> list[Candidate]:
    query = f"releasegroup:({_lucene(title)}) AND artist:({_lucene(artist)})"
    data = http.get_json(f"{MB_API}/release-group/", {"query": query, "fmt": "json", "limit": 25})
    out = []
    for g in data.get("release-groups", []):
        credit = "".join(c.get("name", "") + (c.get("joinphrase") or "") for c in g.get("artist-credit", []))
        out.append(
            Candidate(
                id=g["id"],
                title=g["title"],
                artist=credit,
                year=(g.get("first-release-date") or "")[:4] or None,
                primary_type=g.get("primary-type"),
                secondary_types=tuple(g.get("secondary-types") or ()),
                score=int(g.get("score", 0)),
                disambiguation=g.get("disambiguation") or "",
            )
        )
    return out


@dataclass
class Match:
    best: Candidate | None
    ambiguous: list[Candidate]  # empty when `best` is a confident pick


def choose_release_group(candidates: list[Candidate], artist: str, title: str, year: str | None) -> Match:
    """Pick the release group for a local album, or report the close calls.

    Ranked by title similarity, then album over single/EP, then a plain studio album over
    live/compilation/remix. Local year only breaks ties: tags often carry a reissue's year.
    """
    titles = {title, clean_title(title)}

    def key(c: Candidate) -> tuple:
        sim = max(similar(t, n) for t in titles for n in c.names)
        return (round(sim, 2), c.primary_type == "Album", not c.secondary_types)

    plausible = [c for c in candidates if similar(artist, c.artist) >= MATCH and key(c)[0] >= MATCH]
    if not plausible:
        return Match(None, [])
    top = max(key(c) for c in plausible)
    tied = [c for c in plausible if key(c) == top]
    if len(tied) > 1 and year:
        same_year = [c for c in tied if c.year == year[:4]]
        if len(same_year) == 1:
            return Match(same_year[0], [])
    if len(tied) > 1:
        return Match(None, sorted(tied, key=lambda c: c.year or "9999"))
    return Match(tied[0], [])


# --- Cover art -------------------------------------------------------------------


def caa_front(http: Http, release_group: str) -> Cover | None:
    try:
        data = http.get_json(f"{CAA_API}/release-group/{release_group}")
    except NotFound:
        return None
    front = next((i for i in data.get("images", []) if i.get("front")), None)
    if not front:
        return None
    thumbs = front.get("thumbnails", {})
    url = thumbs.get(str(ART_SIZE)) or front.get("image")
    try:
        return cover_from_bytes(http.get_bytes(url), f"caa:{release_group}")
    except NotFound:
        return None


def itunes_front(http: Http, artist: str, title: str) -> Cover | None:
    data = http.get_json(ITUNES_API, {"term": f"{artist} {clean_title(title)}", "entity": "album", "limit": 10})
    for r in data.get("results", []):
        if similar(artist, r.get("artistName", "")) >= MATCH and max(
            similar(t, r.get("collectionName", "")) for t in (title, clean_title(title))
        ) >= MATCH:
            url = r.get("artworkUrl100", "").replace("100x100bb", f"{ART_SIZE}x{ART_SIZE}bb")
            if url:
                try:
                    return cover_from_bytes(http.get_bytes(url), f"itunes:{r.get('collectionId')}")
                except NotFound:
                    continue
    return None


# --- Stage -----------------------------------------------------------------------


def lookup_art(album: Album, work_dir: Path, http: Http) -> str:
    """Try to replace missing or low-res art. Updates `album` and files in place.

    Returns a one-line summary of what happened.
    """
    if album.release_group:  # pinned during curation, or found on an earlier run
        rg, note = album.release_group, "pinned"
        album.needs_review, album.candidates = False, []
    else:
        match = choose_release_group(search_release_groups(http, album.artist, album.title), album.artist, album.title, album.year)
        if match.ambiguous:
            album.needs_review = True
            album.candidates = [c.describe() for c in match.ambiguous[:8]]
            return f"ambiguous ({len(match.ambiguous)} candidates), set release_group in album.json to pick one"
        rg, note = (match.best.id, "matched") if match.best else (None, "no MusicBrainz match")
        if match.best:
            album.release_group = rg
            album.original_year = match.best.year

    cover = (caa_front(http, rg) if rg else None) or itunes_front(http, album.artist, album.title)
    if cover is None:
        return f"{note}; no online art found"
    if album.art_px and cover.px <= album.art_px:
        return f"{note}; online art {cover.px}px is no better than local {album.art_px}px"

    for old in work_dir.glob("cover.*"):
        if album.art_source and not album.art_source.startswith(("caa:", "itunes:")):
            old.rename(work_dir / f"cover-local{old.suffix}")  # kept so a wrong match can be spotted
        else:
            old.unlink()
    album.art_file = f"cover{cover.ext}"
    album.art_source, album.art_px = cover.source, cover.px
    (work_dir / album.art_file).write_bytes(cover.data)
    if cover.px >= art_px_needed() and "art" in album.needs:
        album.needs.remove("art")
    return f"{note}; art {cover.px}px from {cover.source.split(':')[0]}"
