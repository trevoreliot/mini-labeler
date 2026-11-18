"""HTTP with an on-disk cache, per-host rate limits and retries on 503."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

from md_labeler.config import USER_AGENT

CACHE_DIR = Path("cache")
# Minimum seconds between requests to a host. MusicBrainz bans clients that exceed 1/s;
# Apple asks for about 20/min.
MIN_INTERVAL = {"musicbrainz.org": 1.1, "itunes.apple.com": 3.0}
RETRIES = 4


class NotFound(Exception):
    pass


class Http:
    def __init__(self, cache_dir: Path = CACHE_DIR, refresh: bool = False):
        self.cache_dir = cache_dir
        self.refresh = refresh  # ignore cached responses (still writes new ones)
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
        self._last: dict[str, float] = {}

    def get_json(self, url: str, params: dict | None = None) -> dict:
        return json.loads(self._get(url, params, ".json"))

    def get_bytes(self, url: str) -> bytes:
        return self._get(url, None, ".bin")

    def _get(self, url: str, params: dict | None, suffix: str) -> bytes:
        full = f"{url}?{urlencode(sorted(params.items()))}" if params else url
        path = self.cache_dir / (hashlib.sha256(full.encode()).hexdigest()[:32] + suffix)
        missing = path.with_suffix(".404")
        if not self.refresh:
            if path.exists():
                return path.read_bytes()
            if missing.exists():
                raise NotFound(full)

        for attempt in range(RETRIES):
            self._wait(urlsplit(full).hostname or "")
            r = self.client.get(full)
            if r.status_code == 404:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                missing.write_text(full + "\n")
                raise NotFound(full)
            if r.status_code in (429, 503) and attempt < RETRIES - 1:
                time.sleep(float(r.headers.get("retry-after", 0)) or 2**attempt * 2)
                continue
            r.raise_for_status()
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return r.content
        raise AssertionError("unreachable")

    def _wait(self, host: str) -> None:
        interval = next((v for h, v in MIN_INTERVAL.items() if host == h or host.endswith("." + h)), 0.0)
        wait = self._last.get(host, 0.0) + interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()
