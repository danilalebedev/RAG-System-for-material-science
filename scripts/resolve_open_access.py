from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.web_search.open_access import resolve_open_access  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve legal open-access full text for a publication.")
    parser.add_argument("--doi", default="", help="Publication DOI.")
    parser.add_argument("--title", default="", help="Publication title when DOI is unavailable.")
    parser.add_argument("--year", default="", help="Publication year.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = resolve_open_access(doi=args.doi, title=args.title, year=args.year)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
