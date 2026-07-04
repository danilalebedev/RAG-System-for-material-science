from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market.radar import production_dashboard_rows, run_market_radar  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Agent F / Production Radar. Thin alias for Oreacle Market Radar."
    )
    parser.add_argument("query", nargs="+", help="Production intelligence query.")
    parser.add_argument("--json", action="store_true", help="Print full structured Market Radar JSON.")
    parser.add_argument("--no-demo-fixtures", action="store_true", help="Disable built-in fallback fixtures.")
    return parser.parse_args()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    args = parse_args()
    query = " ".join(args.query)
    result = run_market_radar(query, demo_mode=not args.no_demo_fixtures)
    payload = result.as_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    compact = {
        "agent": "Agent F - Business / Production Radar",
        "detected": payload["detected"],
        "selected_sources": [
            {
                "source_id": item["source_id"],
                "source_name": item["source_name"],
                "source_url": item["source_url"],
            }
            for item in payload["selected_sources"]
        ],
        "dashboard_rows": production_dashboard_rows(result.production_rows),
        "production_rows": payload["production_rows"],
        "market_summary": payload["market_summary"],
        "source_status": payload["source_status"],
        "missing_data": payload["missing_data"],
    }
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
