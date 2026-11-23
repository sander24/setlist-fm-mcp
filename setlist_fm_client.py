"""Client for the setlist.fm REST API.

Responses are cached on disk (SQLite via requests-cache) to save API quota.
This module never prints: it returns data and reports cache hits through the
`logging` module (stderr), so it is safe to use from an MCP server where stdout
carries the protocol.
"""

import logging
import os
from datetime import timedelta
from pathlib import Path

import requests_cache
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent / ".env")
API_KEY = os.environ.get("SETLISTFM_API_KEY")
if not API_KEY:
    raise RuntimeError("SETLISTFM_API_KEY is not set. Copy .env.example to .env and add your key.")

BASE_URL = "https://api.setlist.fm/rest/1.0"
# SETLISTFM_CACHE_PATH points at another cache file (e.g. a throwaway one for the smoke test).
CACHE_PATH = Path(
    os.environ.get("SETLISTFM_CACHE_PATH", Path(__file__).resolve().parent / ".cache" / "setlistfm")
)

session = requests_cache.CachedSession(
    str(CACHE_PATH),
    backend="sqlite",
    expire_after=timedelta(days=1),
    urls_expire_after={
        "api.setlist.fm/rest/1.0/search/artists*": timedelta(days=7),
        "api.setlist.fm/rest/1.0/artist/*/setlists*": timedelta(days=1),
        "api.setlist.fm/rest/1.0/setlist/*": timedelta(days=30),
        "api.setlist.fm/rest/1.0/artist/*": timedelta(days=30),
    },
    allowable_codes=(200, 404),  # also cache "not found" to avoid repeat misses
    # Redact the API key header from stored requests (and keep it out of the cache key),
    # so cache files never contain the key.
    ignored_parameters=["x-api-key"],
)
# Retry rate-limited (429) and transient server errors with exponential backoff.
# Failed responses are never cached (not in allowable_codes).
session.mount(
    "https://",
    HTTPAdapter(
        max_retries=Retry(
            total=4,
            backoff_factor=1,  # 1s, 2s, 4s, 8s
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
    ),
)
session.headers.update(
    {
        "x-api-key": API_KEY,
        "Accept": "application/json",
        "Accept-Language": "en",
    }
)


def _get(path: str, params: dict) -> dict | None:
    """GET an API path; return parsed JSON, or None on 404. Raises on other errors."""
    resp = session.get(f"{BASE_URL}{path}", params=params, timeout=15)
    source = "cache" if resp.from_cache else "API"
    logger.info("GET %s -> HTTP %s (from %s)", resp.url, resp.status_code, source)

    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def search_artists(artist_name: str, page: int = 1, sort: str = "relevance") -> dict | None:
    """Return the artist search result, or None if no artists were found."""
    return _get("/search/artists", {"artistName": artist_name, "p": page, "sort": sort})


def get_setlists_by_artist_mbid(mbid: str, page: int = 1) -> dict | None:
    """Return a page of setlists for the artist with the given MusicBrainz ID,
    or None if the artist/page has no setlists."""
    return _get(f"/artist/{mbid}/setlists", {"p": page})


def get_setlists_by_artist_name(artist_name: str, page: int = 1) -> dict | None:
    """Look up an artist by name and return a page of their setlists.

    Picks the search result whose name matches exactly (case-insensitive),
    otherwise the most relevant one. Returns None if no artist was found.

    Result:
        {
            "artist": {...},          # the artist the setlists belong to
            "otherMatches": [...],    # other search results, for disambiguation
            "setlists": {...} | None, # get_setlists_by_artist_mbid() result
        }
    """
    found = search_artists(artist_name)
    artists = (found or {}).get("artist", [])
    if not artists:
        return None

    artist = next(
        (a for a in artists if a.get("name", "").casefold() == artist_name.casefold()),
        artists[0],
    )
    return {
        "artist": artist,
        "otherMatches": [a for a in artists if a is not artist],
        "setlists": get_setlists_by_artist_mbid(artist["mbid"], page),
    }
