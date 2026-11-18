import httpx
import pytest

from md_labeler.fetch import http as http_mod
from md_labeler.fetch.http import Http, NotFound


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_caches_hits_and_404s(tmp_path):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(404) if "missing" in str(req.url) else httpx.Response(200, json={"ok": 1})

    h = Http(cache_dir=tmp_path)
    h.client = _client(handler)
    assert h.get_json("https://example.com/a", {"q": "x"}) == {"ok": 1}
    assert h.get_json("https://example.com/a", {"q": "x"}) == {"ok": 1}
    for _ in range(2):
        with pytest.raises(NotFound):
            h.get_bytes("https://example.com/missing")
    assert len(seen) == 2  # second calls came from the cache

    fresh = Http(cache_dir=tmp_path, refresh=True)
    fresh.client = _client(handler)
    fresh.get_json("https://example.com/a", {"q": "x"})
    assert len(seen) == 3


def test_retries_503(tmp_path, monkeypatch):
    monkeypatch.setattr(http_mod.time, "sleep", lambda s: None)
    responses = iter([httpx.Response(503), httpx.Response(503), httpx.Response(200, content=b"img")])
    h = Http(cache_dir=tmp_path)
    h.client = _client(lambda req: next(responses))
    assert h.get_bytes("https://example.com/img") == b"img"
