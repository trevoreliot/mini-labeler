"""User and network settings. Each can be overridden with an environment variable."""

import os
from importlib.metadata import version
from pathlib import Path


def _env(name: str, default: str | None) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or default


# MusicBrainz requires contact info (an email or URL) in the User-Agent:
# https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting
CONTACT = _env("MD_LABELER_CONTACT", "https://github.com/trevoreliot")
USER_AGENT = f"md-labeler/{version('md-labeler')} ( {CONTACT} )"

# Music library laid out as <root>/<artist>/<album>/<tracks>, browsed by `mdl pick`.
MUSIC_ROOT = Path(_env("MD_LABELER_MUSIC_ROOT", "/mnt/ssd500/Media/Music")).expanduser()

# CUPS printer for `mdl print`. None means the system default (`lpstat -d`).
PRINTER: str | None = _env("MD_LABELER_PRINTER", None)
