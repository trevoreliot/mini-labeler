import io
from pathlib import Path

import pytest
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TPE2, TRCK
from PIL import Image

from md_labeler.albumlist import AlbumEntry, read_album_list, write_album_list
from md_labeler.fetch import fetch_entry
from md_labeler.fetch.local import find_cover, read_album
from md_labeler.models import Album
from md_labeler.picker import scan_library

# One silent MPEG-1 Layer III frame: 128 kbps, 44.1 kHz -> 417 bytes.
MP3_FRAME = b"\xff\xfb\x90\x00" + b"\x00" * 413


def _png(px: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (px, px), "red").save(buf, "PNG")
    return buf.getvalue()


def _mp3(path: Path, title=None, track=None, art: bytes | None = None, pic_type=3, **album) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(MP3_FRAME * 40)
    tags = ID3()
    if title:
        tags.add(TIT2(encoding=3, text=title))
    if track:
        tags.add(TRCK(encoding=3, text=track))
    if a := album.get("artist"):
        tags.add(TPE1(encoding=3, text=a))
    if a := album.get("albumartist"):
        tags.add(TPE2(encoding=3, text=a))
    if a := album.get("album"):
        tags.add(TALB(encoding=3, text=a))
    if a := album.get("date"):
        tags.add(TDRC(encoding=3, text=a))
    if art:
        tags.add(APIC(encoding=3, mime="image/png", type=pic_type, desc="", data=art))
    tags.save(path)
    return path


def test_album_list_round_trip(tmp_path):
    entries = [AlbumEntry("AC DC", "Back in Black", Path("/m/AC DC/Back in Black")), AlbumEntry("Talking Heads", "Remain in Light - Deluxe")]
    path = tmp_path / "l.txt"
    write_album_list(path, entries)
    path.write_text("# comment\n\n" + path.read_text())
    assert read_album_list(path) == entries


def test_album_list_rejects_bad_line(tmp_path):
    (tmp_path / "l.txt").write_text("just a name\n")
    with pytest.raises(ValueError, match=":1:"):
        read_album_list(tmp_path / "l.txt")


def test_read_album_prefers_tags(tmp_path):
    d = tmp_path / "AC DC" / "Back in Black"
    common = dict(artist="AC/DC", album="Back in Black", date="1980-07-25")
    _mp3(d / "b.mp3", "Shoot to Thrill", "2/10", **common)
    _mp3(d / "a.mp3", "Hells Bells", "1/10", **common)
    album, cover = read_album(d, "AC DC", "Back in Black")
    assert (album.artist, album.title, album.year) == ("AC/DC", "Back in Black", "1980")
    assert [(t.number, t.title) for t in album.tracks] == [(1, "Hells Bells"), (2, "Shoot to Thrill")]
    assert album.tracks[0].duration == pytest.approx(40 * 1152 / 44100, rel=0.05)
    assert album.needs == [] and cover is None


def test_read_album_falls_back_to_names(tmp_path):
    d = tmp_path / "Artist" / "Album"
    _mp3(d / "03 - Third Song.mp3")
    album, _ = read_album(d, "Artist", "Album")
    assert (album.artist, album.title) == ("Artist", "Album")
    assert album.tracks[0].title == "Third Song"
    assert "tracks" in album.needs


def test_cover_prefers_front_then_resolution(tmp_path):
    d = tmp_path / "A" / "B"
    f = _mp3(d / "1.mp3", "x", "1", art=_png(400))  # embedded front cover
    _mp3(d / "2.mp3", "y", "2", art=_png(1200), pic_type=4)  # bigger, but a back cover
    (d / "scan.png").write_bytes(_png(900))  # folder image not named like a cover
    assert find_cover(d, [f, d / "2.mp3"]).px == 400
    (d / "folder.png").write_bytes(_png(700))
    c = find_cover(d, [f, d / "2.mp3"])
    assert (c.px, c.source) == (700, "folder:folder.png")


def test_fetch_entry_writes_work_dir_and_flags_needs(tmp_path):
    d = tmp_path / "music" / "A" / "B"
    _mp3(d / "1.mp3", "One", "1", art=_png(500), album="B", artist="A")
    r = fetch_entry(AlbumEntry("A", "B", d), work_dir=tmp_path / "work")
    album = Album.load(r.dir / "album.json")
    assert album.art_file == "cover.png" and album.art_px == 500
    assert (r.dir / "cover.png").exists()
    assert album.needs == ["art"]  # 500 px is below what a 72 mm label needs at 300 dpi

    album.spine_text = "curated"
    album.save(r.dir / "album.json")
    assert fetch_entry(AlbumEntry("A", "B", d), work_dir=tmp_path / "work").album.spine_text == "curated"
    assert fetch_entry(AlbumEntry("A", "B", d), work_dir=tmp_path / "work", force=True).album.spine_text is None


def test_fetch_entry_without_folder(tmp_path):
    r = fetch_entry(AlbumEntry("Talking Heads", "Remain in Light"), work_dir=tmp_path)
    assert r.album.needs == ["tracks", "art"]


def test_scan_library_lists_only_album_folders(tmp_path):
    _mp3(tmp_path / "Zed" / "Two" / "1.mp3")
    _mp3(tmp_path / "abba" / "One" / "1.mp3")
    (tmp_path / "Playlists" / "empty").mkdir(parents=True)
    lib = scan_library(tmp_path)
    assert list(lib) == ["abba", "Zed"]
    assert [p.name for p in lib["Zed"]] == ["Two"]


def test_strips_track_number_from_title_tags(tmp_path):
    d = tmp_path / "A" / "B"
    _mp3(d / "1.mp3", "01 - Son Et Lumiere", "1")
    _mp3(d / "2.mp3", "1979", "2")  # a number that is the title, not the track number
    album, _ = read_album(d, "A", "B")
    assert [t.title for t in album.tracks] == ["Son Et Lumiere", "1979"]
