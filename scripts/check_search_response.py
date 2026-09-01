#!/usr/bin/env python3
"""Assert one search response is usable for the requested retrieval mode.

Used by the container smoke test so the shell script does not have to parse
JSON itself. Reads the response body on standard input.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    """Validate the response shape and print a one-line summary."""

    if len(sys.argv) != 2:
        print("usage: check_search_response.py <mode>", file=sys.stderr)
        return 2

    mode = sys.argv[1]
    payload = json.load(sys.stdin)
    results = payload["results"]

    if payload["mode"] != mode:
        print(f"expected mode {mode}, got {payload['mode']}", file=sys.stderr)
        return 1
    if not results:
        print(f"{mode} returned no results", file=sys.stderr)
        return 1
    if results[0]["score_components"]["method"] != mode:
        print(f"{mode} returned score components for another method", file=sys.stderr)
        return 1

    print(f"    {mode}: {len(results)} results, top={results[0]['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
