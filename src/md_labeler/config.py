"""User and network settings."""

from importlib.metadata import version

# MusicBrainz requires contact info in the User-Agent: https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
CONTACT = "https://github.com/trevoreliot"
USER_AGENT = f"md-labeler/{version('md-labeler')} ( {CONTACT} )"

# CUPS printer for `mdl print`. None means the system default (`lpstat -d`).
PRINTER: str | None = None
