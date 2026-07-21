"""Fallback album art lookup via the iTunes Search API.

Some sources (AirPlay in particular) report no album art at all. Rather than leave
the UI showing a bare glyph, look up a matching cover on iTunes -- but only ever
use it when the returned artist/track is a confident match; otherwise leave the
result blank exactly as the device does.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

_LOGGER = logging.getLogger(__name__)

SEARCH_URL = "https://itunes.apple.com/search"


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _matches(requested: str, returned: str) -> bool:
    requested = _normalize(requested)
    returned = _normalize(returned)
    if not requested or not returned:
        return False
    return requested in returned or returned in requested


class AlbumArtLookup:
    """Looks up cover art for a track, with an in-process TTL cache.

    Failures of any kind (network error, timeout, no confident match) resolve to
    "" rather than raising -- a flaky external API must never break /api/state or
    the SSE feed.
    """

    def __init__(self, timeout: float = 3.0, ttl: float = 3600.0):
        self.timeout = timeout
        self.ttl = ttl
        self._session = requests.Session()
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}
        self._lock = threading.Lock()

    def lookup(self, artist: str, track: str) -> str:
        artist = (artist or "").strip()
        track = (track or "").strip()
        if not artist and not track:
            return ""

        key = (_normalize(artist), _normalize(track))
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and cached[1] > now:
                return cached[0]

        art_url = self._search(artist, track)
        with self._lock:
            self._cache[key] = (art_url, now + self.ttl)
        return art_url

    def _search(self, artist: str, track: str) -> str:
        term = " ".join(part for part in (artist, track) if part)
        try:
            response = self._session.get(
                SEARCH_URL,
                params={"term": term, "media": "music", "entity": "song", "limit": 5},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as err:
            _LOGGER.debug("album art lookup failed for %r: %s", term, err)
            return ""

        for result in payload.get("results", []):
            if _matches(artist, result.get("artistName", "")) and _matches(
                track, result.get("trackName", "")
            ):
                artwork = result.get("artworkUrl100", "")
                if artwork:
                    return artwork.replace("100x100", "600x600")
        return ""
