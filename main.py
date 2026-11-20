#!/usr/bin/env python3
"""Manual test runner: calls the setlist.fm client and prints the results."""

import json
import logging
import sys

from setlist_fm_mcp import get_artist_setlists, search_artists

VENNASKOND_MBID = "06ec7d7a-c91d-4e50-8f98-83ac674a3344"


def print_banner(title: str, *details: str) -> None:
    """Print a framed multi-line banner so each step stands out in the console."""
    lines = [title, *details]
    width = max(len(line) for line in lines) + 4
    print()
    print("#" * (width + 2))
    print("#" + " " * width + "#")
    for line in lines:
        print("#  " + line.ljust(width - 2) + "#")
    print("#" + " " * width + "#")
    print("#" * (width + 2))
    print()


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
        print(f"\n* {s.get('eventDate')}  {place}")
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


def run_search_artist(artist_name: str) -> None:
    try:
        data = search_artists(artist_name)
    except Exception as e:  # network errors, 429, 5xx, ...
        print(f"Request failed: {e}", file=sys.stderr)
        sys.exit(1)

    if data is None:
        print(f"No artists found for '{artist_name}'.")
        return

    print("JSON response:")
    print(json.dumps(data, indent=3, ensure_ascii=False))
    print()

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
    print_banner("GET ARTIST SETLISTS", f"Artist MBID: {mbid}", f"Page:        {page}")
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
    # Show the client's "GET ... (from cache/API)" lines.
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("setlist_fm_mcp").setLevel(logging.INFO)

    # run_search_artist(sys.argv[1] if len(sys.argv) > 1 else "Vennaskond")
    run_get_setlist(sys.argv[1] if len(sys.argv) > 1 else VENNASKOND_MBID)


if __name__ == "__main__":
    main()
