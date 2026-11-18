import io

import pytest
from PIL import Image

from md_labeler.fetch.http import NotFound
from md_labeler.fetch.online import CAA_API, ITUNES_API, MB_API, Candidate, choose_release_group, clean_title, lookup_art
from md_labeler.models import Album


def _jpeg(px: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (px, px), "blue").save(buf, "JPEG")
    return buf.getvalue()


def _rg(id, title, kind="Album", secondary=(), year="2003", artist="Linkin Park", score=100):
    return {
        "id": id,
        "title": title,
        "primary-type": kind,
        "secondary-types": list(secondary),
        "first-release-date": year,
        "score": score,
        "artist-credit": [{"name": artist}],
    }


METEORA = [  # shaped like the live MusicBrainz response
    _rg("single", "Meteora", kind="Single", year="2023-06-24"),
    _rg("album", "Meteora", year="2003-03-24"),
    _rg("live", "Meteora Hamburg", secondary=["Live"]),
    _rg("anniv", "Meteora (20th anniversary edition)", secondary=["Compilation"], year="2023-03-24"),
]


def _candidates(groups):
    return [
        Candidate(g["id"], g["title"], g["artist-credit"][0]["name"], g["first-release-date"][:4], g["primary-type"], tuple(g["secondary-types"]), g["score"])
        for g in groups
    ]


class FakeHttp:
    def __init__(self, json=None, files=None):
        self.json, self.files, self.calls = json or {}, files or {}, []

    def get_json(self, url, params=None):
        self.calls.append(url)
        if url not in self.json:
            raise NotFound(url)
        return self.json[url]

    def get_bytes(self, url):
        self.calls.append(url)
        if url not in self.files:
            raise NotFound(url)
        return self.files[url]


def _caa(rg, url):
    return {f"{CAA_API}/release-group/{rg}": {"images": [{"front": True, "image": url + "-orig", "thumbnails": {"1200": url}}]}}


@pytest.mark.parametrize(
    ("title", "clean"),
    [
        ("Random Access Memories (2 Vinyl, LP)", "Random Access Memories"),
        ("A Fever You Can't Sweat Out (Japanese Limited Edition)", "A Fever You Can't Sweat Out"),
        ("Abbey Road [Remastered 2009]", "Abbey Road"),
        ("Weezer (Teal Album)", "Weezer (Teal Album)"),
        ("(What's the Story) Morning Glory?", "(What's the Story) Morning Glory?"),
    ],
)
def test_clean_title(title, clean):
    assert clean_title(title) == clean


def test_prefers_album_over_same_named_single_and_variants():
    m = choose_release_group(_candidates(METEORA), "Linkin Park", "Meteora", "2003")
    assert m.best.id == "album" and not m.ambiguous


def test_matches_through_punctuation_and_edition_notes():
    groups = [_rg("ram", "Random Access Memories", artist="Daft Punk", year="2013")]
    m = choose_release_group(_candidates(groups), "Daft Punk", "Random Access Memories (2 Vinyl, LP)", "2013")
    assert m.best.id == "ram"
    groups = [_rg("bib", "Back in Black", artist="AC/DC", year="1980")]
    assert choose_release_group(_candidates(groups), "AC DC", "Back in Black", None).best.id == "bib"


def test_same_titled_albums_are_ambiguous_unless_year_decides():
    weezer = [_rg(c, "Weezer", artist="Weezer", year=y) for c, y in (("blue", "1994"), ("green", "2001"), ("red", "2008"))]
    m = choose_release_group(_candidates(weezer), "Weezer", "Weezer", None)
    assert m.best is None and [c.id for c in m.ambiguous] == ["blue", "green", "red"]
    assert choose_release_group(_candidates(weezer), "Weezer", "Weezer", "2001").best.id == "green"


def test_disambiguation_counts_as_part_of_the_title():
    weezer = [
        Candidate(c, "Weezer", "Weezer", y, "Album", (), 100, d)
        for c, y, d in (("blue", "1994", "Blue Album"), ("teal", "2019", "Teal Album"), ("black", "2019", "Black Album"))
    ]
    assert choose_release_group(weezer, "Weezer", "Weezer (Teal Album)", "2019").best.id == "teal"
    m = choose_release_group(weezer, "Weezer", "Weezer", "2019")  # Teal and Black both came out in 2019
    assert m.best is None and {c.id for c in m.ambiguous} == {"blue", "teal", "black"}


def test_no_match_for_wrong_artist():
    assert choose_release_group(_candidates(METEORA), "Linkin", "Hybrid Theory", None).best is None


def test_lookup_replaces_low_res_art_and_keeps_local_copy(tmp_path):
    (tmp_path / "cover.jpg").write_bytes(_jpeg(300))
    album = Album("Linkin Park", "Meteora", "2003", art_file="cover.jpg", art_source="embedded:x.mp3", art_px=300, needs=["art"])
    http = FakeHttp({f"{MB_API}/release-group/": {"release-groups": METEORA}, **_caa("album", "img")}, {"img": _jpeg(1200)})

    note = lookup_art(album, tmp_path, http)
    assert "1200px from caa" in note
    assert (album.release_group, album.original_year, album.art_px) == ("album", "2003", 1200)
    assert album.art_source == "caa:album" and album.needs == []
    assert (tmp_path / "cover-local.jpg").exists() and (tmp_path / "cover.jpg").read_bytes() == _jpeg(1200)


def test_falls_back_to_itunes_when_caa_has_nothing(tmp_path):
    album = Album("Linkin Park", "Meteora", needs=["art"])
    url = "https://is1.example/abc/100x100bb.jpg"
    http = FakeHttp(
        {
            f"{MB_API}/release-group/": {"release-groups": METEORA},
            ITUNES_API: {"results": [{"artistName": "LINKIN PARK", "collectionName": "Meteora", "collectionId": 7, "artworkUrl100": url}]},
        },
        {url.replace("100x100bb", "1200x1200bb"): _jpeg(1200)},
    )
    assert "from itunes" in lookup_art(album, tmp_path, http)
    assert album.art_source == "itunes:7" and not list(tmp_path.glob("cover-local.*"))


def test_keeps_local_art_when_online_is_not_better(tmp_path):
    album = Album("Linkin Park", "Meteora", art_file="cover.jpg", art_source="embedded:x", art_px=800, needs=["art"])
    (tmp_path / "cover.jpg").write_bytes(b"local")
    http = FakeHttp({f"{MB_API}/release-group/": {"release-groups": METEORA}, **_caa("album", "img")}, {"img": _jpeg(500)})
    assert "no better" in lookup_art(album, tmp_path, http)
    assert album.art_px == 800 and (tmp_path / "cover.jpg").read_bytes() == b"local"


def test_ambiguous_match_flags_review_and_pinning_resolves_it(tmp_path):
    weezer = [_rg(c, "Weezer", artist="Weezer", year=y) for c, y in (("blue", "1994"), ("green", "2001"))]
    album = Album("Weezer", "Weezer", needs=["art"])
    http = FakeHttp({f"{MB_API}/release-group/": {"release-groups": weezer}, **_caa("green", "img")}, {"img": _jpeg(1200)})
    assert "ambiguous" in lookup_art(album, tmp_path, http)
    assert album.needs_review and len(album.candidates) == 2 and album.art_file is None

    album.release_group = "green"  # what curation does
    http.calls.clear()
    assert lookup_art(album, tmp_path, http).startswith("known release group")
    assert not album.needs_review and album.art_px == 1200
    assert not any("musicbrainz" in c for c in http.calls)  # no search when pinned


# --- Track lists ---------------------------------------------------------------

from md_labeler.fetch.online import Release, choose_release, edition_words, lookup_tracks  # noqa: E402
from md_labeler.models import Track  # noqa: E402


def _release(id, date="2003", status="Official", formats=("CD",), count=13, title="Meteora", dis=""):
    return Release(id, title, status, date, dis, formats, count)


def _browse_json(releases):
    return {
        "release-count": len(releases),
        "releases": [
            {"id": r.id, "title": r.title, "status": r.status, "date": r.date, "disambiguation": r.disambiguation,
             "media": [{"format": f, "track-count": r.track_count // len(r.formats)} for f in r.formats]}
            for r in releases
        ],
    }


def _release_json(titles_by_disc, formats=None):
    media = []
    for i, titles in enumerate(titles_by_disc):
        media.append({"format": (formats or ["CD"] * len(titles_by_disc))[i],
                      "tracks": [{"position": n, "title": t, "length": 200_000 + n} for n, t in enumerate(titles, 1)]})
    return {"media": media}


def test_edition_words():
    assert clean_title("Remain in Light - Deluxe") == "Remain in Light"
    assert edition_words("Abbey Road (Remastered 2009)") == {"remaster"}
    assert edition_words("A Fever You Can't Sweat Out (Japanese Limited Edition)") == {"japan", "limited"}
    assert edition_words("Meteora") == set()


def test_choose_release_prefers_official_plain_cd_earliest():
    releases = [
        _release("boot", status="Bootleg", date="2002"),
        _release("special", dis="special edition", date="2003-03-01"),
        _release("vinyl", formats=("Vinyl", "Vinyl"), date="2003-03-01"),
        _release("cd-late", date="2004"),
        _release("cd", date="2003-03-25"),
        _release("dvd-only", formats=(), count=0, date="2001"),
    ]
    assert choose_release(releases, set(), None).id == "cd"


def test_choose_release_honours_requested_edition_and_local_count():
    releases = [_release("std", date="2003"), _release("deluxe", title="Meteora (Deluxe)", count=20, date="2013")]
    assert choose_release(releases, {"deluxe"}, None).id == "deluxe"
    releases = [_release("us", date="2003", count=13), _release("jp", date="2003", count=14, dis="")]
    assert choose_release(releases, set(), 14).id == "jp"  # matches the files the user has


def test_lookup_tracks_fills_album_from_musicbrainz():
    rgs = {f"{MB_API}/release-group/": {"release-groups": METEORA}}
    browse = {f"{MB_API}/release": _browse_json([_release("cd"), _release("vinyl", formats=("Vinyl", "Vinyl"))])}
    rel = {f"{MB_API}/release/cd": _release_json([["Foreword", "Don't Stay"], ["Bonus"]])}
    album = Album("Linkin Park", "Meteora", needs=["tracks", "art"])
    note = lookup_tracks(album, FakeHttp({**rgs, **browse, **rel}))
    assert "3 tracks" in note and "CD" in note
    assert [(t.disc, t.number, t.title) for t in album.tracks] == [(1, 1, "Foreword"), (1, 2, "Don't Stay"), (2, 1, "Bonus")]
    assert album.tracks[0].duration == pytest.approx(200.001)
    assert album.mbid == "cd" and album.tracks_source == "musicbrainz:cd"
    assert album.needs == ["art"] and album.release_group == "album"


def test_lookup_tracks_keeps_local_durations_when_counts_match():
    rel = _release_json([["A", "B"]])
    for t in rel["media"][0]["tracks"]:
        t["length"] = None
    http = FakeHttp({f"{MB_API}/release": _browse_json([_release("r", count=2)]), f"{MB_API}/release/r": rel})
    album = Album("X", "Y", release_group="rg", tracks=[Track(1, "01 a", 61.0), Track(2, "02 b", 62.0)], needs=["tracks"])
    lookup_tracks(album, http)
    assert [(t.title, t.duration) for t in album.tracks] == [("A", 61.0), ("B", 62.0)]


def test_lookup_tracks_ambiguous_leaves_album_alone():
    weezer = [_rg(c, "Weezer", artist="Weezer", year=y) for c, y in (("blue", "1994"), ("green", "2001"))]
    album = Album("Weezer", "Weezer", needs=["tracks"])
    assert "ambiguous" in lookup_tracks(album, FakeHttp({f"{MB_API}/release-group/": {"release-groups": weezer}}))
    assert album.needs == ["tracks"] and album.needs_review and album.tracks == []


def test_fetch_entry_without_folder_gets_tracks_then_art(tmp_path):
    from md_labeler.albumlist import AlbumEntry
    from md_labeler.fetch import fetch_entry

    http = FakeHttp(
        {
            f"{MB_API}/release-group/": {"release-groups": METEORA},
            f"{MB_API}/release": _browse_json([_release("cd", count=2)]),
            f"{MB_API}/release/cd": _release_json([["Foreword", "Don't Stay"]]),
            **_caa("album", "img"),
        },
        {"img": _jpeg(1200)},
    )
    r = fetch_entry(AlbumEntry("Linkin Park", "Meteora"), work_dir=tmp_path, http=http)
    assert [n.split(":")[0] for n in r.online] == ["tracks", "art"]
    assert r.album.needs == [] and len(r.album.tracks) == 2 and r.album.art_px == 1200
    assert sum("release-group/" in c and "musicbrainz" in c for c in http.calls) == 1  # identified once
    assert (r.dir / "palette.json").exists()
