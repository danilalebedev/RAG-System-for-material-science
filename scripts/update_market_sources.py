from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.market.parsers import fixture_rows  # noqa: E402


DEFAULT_CACHE_PATH = ROOT / "data" / "processed" / "market_cache" / "market_rows.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a small normalized Market Radar cache.")
    parser.add_argument("--output", type=Path, default=DEFAULT_CACHE_PATH, help="Output JSON path.")
    parser.add_argument(
        "--demo-fixtures",
        action="store_true",
        default=True,
        help="Write built-in demo fixtures. Live downloads are intentionally not enabled.",
    )
    return parser.parse_args()


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    args = parse_args()
    rows = [row.model_dump(mode="json") for row in fixture_rows()]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "rows": len(rows), "mode": "demo_fixtures"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
