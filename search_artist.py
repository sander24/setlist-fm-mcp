#!/usr/bin/env python3
"""Search for an artist using the setlist.fm API and print the results.

Responses are cached on disk (SQLite via requests-cache) to save API quota.
"""

import os
import sys
from datetime import timedelta
from pathlib import Path

import requests_cache
from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

load_dotenv(Path(__file__).resolve().parent / ".env")
API_KEY = os.environ.get("SETLISTFM_API_KEY")
if not API_KEY:
    sys.exit("SETLISTFM_API_KEY is not set. Copy .env.example to .env and add your key.")
BASE_URL = "https://api.setlist.fm/rest/1.0"
CACHE_PATH = Path(__file__).resolve().parent / ".cache" / "setlistfm"

session = requests_cache.CachedSession(
    str(CACHE_PATH),
    backend="sqlite",
    expire_after=timedelta(days=1),  # default for anything not matched below
    urls_expire_after={
        "api.setlist.fm/rest/1.0/search/artists*": timedelta(days=7),
        "api.setlist.fm/rest/1.0/artist/*/setlists*": timedelta(days=1),
        "api.setlist.fm/rest/1.0/setlist/*": timedelta(days=30),
        "api.setlist.fm/rest/1.0/artist/*": timedelta(days=30),
    },
    allowable_codes=(200, 404),  # also cache "not found" to avoid repeat misses
    # The API key is sent as a header, so it is not part of the cache key.
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


def search_artists(artist_name: str, page: int = 1, sort: str = "relevance") -> dict | None:
    """Return the search result as a dict, or None if no artists were found."""
    resp = session.get(
        f"{BASE_URL}/search/artists",
        params={"artistName": artist_name, "p": page, "sort": sort},
        timeout=15,
    )
    source = "cache" if resp.from_cache else "API"
    print(f"Raw JSON response (from {source}, HTTP {resp.status_code}):")
    print(resp.text)
    print()

    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def get_artist_setlists(mbid: str, page: int = 1) -> dict | None:
    """Return a page of setlists for the artist with the given MusicBrainz ID,
    or None if the artist/page has no setlists."""
    resp = session.get(f"{BASE_URL}/artist/{mbid}/setlists", params={"p": page}, timeout=15)
    source = "cache" if resp.from_cache else "API"
    print(f"Setlists response from {source}, HTTP {resp.status_code}")

    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def print_setlists(data: dict) -> None:
    setlists = data.get("setlist", [])
    print(
        f"{data.get('total', len(setlists))} setlist(s) in total "
        f"(page {data.get('page')}, {data.get('itemsPerPage')} per page):\n"
    )
    for s in setlists:
        venue = s.get("venue", {})
        city = venue.get("city", {})
        place = ", ".join(
            p for p in (venue.get("name"), city.get("name"), city.get("country", {}).get("name")) if p
        )
        print(f"* {s.get('eventDate')}  {place}")
        if s.get("tour"):
            print(f"    tour: {s['tour'].get('name')}")

        sets = s.get("sets", {}).get("set", [])
        if not sets:
            print("    (no songs listed)")
        for st in sets:
            label = st.get("name") or (f"Encore {st['encore']}" if st.get("encore") else "Set")
            songs = [song.get("name") or "?" for song in st.get("song", [])]
            print(f"    {label}: " + "; ".join(songs))
        print(f"    {s.get('url')}")



VENNASKOND_MBID = "06ec7d7a-c91d-4e50-8f98-83ac674a3344"


def run_search_artist(artist_name: str) -> None:
    try:
        data = search_artists(artist_name)
    except Exception as e:  # network errors, 429, 5xx, ...
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if data is None:
        print(f"No artists found for '{artist_name}'.")
        return

    artists = data.get("artist", [])
    print(
        f"Found {data.get('total', len(artists))} artist(s) for '{artist_name}' "
        f"(page {data.get('page')}, {data.get('itemsPerPage')} per page):\n"
    )
    for a in artists:
        line = f"- {a.get('name')}"
        if a.get("disambiguation"):
            line += f" ({a['disambiguation']})"
        print(line)
        print(f"    sortName: {a.get('sortName')}")
        print(f"    mbid:     {a.get('mbid')}")
        print(f"    url:      {a.get('url')}")


def run_get_setlist(mbid: str, page: int = 1) -> None:
    print(f"Setlists for artist {mbid}:")
    try:
        setlists = get_artist_setlists(mbid, page)
    except Exception as e:
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if setlists is None:
        print("No setlists found.")
    else:
        print_setlists(setlists)


def main() -> None:
    # run_search_artist(sys.argv[1] if len(sys.argv) > 1 else "Vennaskond")
    run_get_setlist(sys.argv[1] if len(sys.argv) > 1 else VENNASKOND_MBID)


if __name__ == "__main__":
    main()
