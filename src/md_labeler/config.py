"""User and network settings."""

from importlib.metadata import version
from pathlib import Path

# MusicBrainz requires contact info in the User-Agent: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
CONTACT = "https://github.com/trevoreliot"
USER_AGENT = f"md-labeler/{version('md-labeler')} ( {CONTACT} )"

# Music library laid out as <root>/<artist>/<album>/<tracks>, browsed by `mdl pick`.
MUSIC_ROOT = Path("/mnt/ssd500/Media/Music")

# CUPS printer for `mdl print`. None means the system default (`lpstat -d`).
PRINTER: str | None = None
