#!/usr/bin/env python3
"""Compute ground truth from the frozen setlist.fm fixtures.

Pages through an artist's setlists in the eval fixture cache (fetching and freezing
any page not cached yet) and prints the countries they played in a given year, as
a YAML snippet to paste under `expected.reference` in evals/cases.yaml.

    python evals/ground_truth.py "The National" 2025
"""

import argparse
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS_DIR.parent))
# Must be set before setlist_fm_mcp is imported: it configures its cache at import time.
os.environ["SETLISTFM_CACHE_PATH"] = str(EVALS_DIR / "fixtures" / "setlistfm")
os.environ["SETLISTFM_CACHE_FROZEN"] = "1"

from setlist_fm_mcp import get_setlists_by_artist_name  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("artist")
    parser.add_argument("year", type=int)
    args = parser.parse_args()

    countries: Counter[str] = Counter()
    artist = None
    page = 1
    while True:
        result = get_setlists_by_artist_name(args.artist, page)
        if result is None:
            sys.exit(f"No artist found for {args.artist!r}.")
        artist = result["artist"]
        data = result["setlists"]
        setlists = (data or {}).get("setlist", [])
        if not setlists:
            break

        years = []
        for s in setlists:
            year = datetime.strptime(s["eventDate"], "%d-%m-%Y").year
            years.append(year)
            if year == args.year:
                country = s.get("venue", {}).get("city", {}).get("country", {}).get("name")
                countries[country or "(unknown)"] += 1

        # Setlists are newest first: stop once a whole page is older than the year.
        if max(years) < args.year or page * data["itemsPerPage"] >= data["total"]:
            break
        page += 1

    print(f"# {artist['name']} ({artist['mbid']}), {args.year}: "
          f"{sum(countries.values())} shows, {page} page(s) read")
    print("reference:")
    print(f"  year: {args.year}")
    if not countries:
        print("  countries: []")
    else:
        print("  countries:")
        for name, n in sorted(countries.items()):
            print(f"    - {name}  # {n} show(s)")


if __name__ == "__main__":
    main()
