#!/usr/bin/env python3
"""Compute ground truth from live setlist.fm data.

Pages through an artist's setlists (through the client's normal 1-day cache, the
same one the eval runs use) and prints the countries they played in a given year,
as a YAML snippet to paste under `expected.reference` in evals/cases.yaml.

    python evals/ground_truth.py "The National" 2025
"""

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(EVALS_DIR.parent))
from setlist_fm_client import get_setlists_by_artist_name  # noqa: E402


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
            # A value, not a YAML comment: comments are dropped when cases.yaml is
            # parsed, so the judge would never see the counts.
            print(f"    - {name}: {n} show{'s' if n != 1 else ''}")


if __name__ == "__main__":
    main()
