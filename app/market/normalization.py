from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from app.market.schemas import MarketDataRow


YEAR_RE = re.compile(r"(20\d{2}|19\d{2})")


def normalize_unit_value(value: float | int | str, unit: str) -> tuple[float | str, str, str | None]:
    raw_unit = unit.strip()
    unit_key = raw_unit.lower().replace(".", "").replace(" ", "")
    try:
        numeric_value: float | str = float(str(value).replace(",", "."))
    except ValueError:
        numeric_value = value

    if unit_key in {"mlnt", "milliont", "milliontonnes", "млнт", "млнтонн"}:
        return numeric_value, "Mt", f"Unit normalized from {raw_unit} to Mt."
    if unit_key in {"thousandtonnes", "kt", "тыстт", "тысттонн"}:
        return numeric_value, "kt", None
    if unit_key in {"mt", "milliontonne", "milliontons"}:
        return numeric_value, "Mt", None
    if unit_key in {"t", "tonnes", "tons", "тонн", "тонны"}:
        return numeric_value, "t", None
    if unit_key in {"koz", "thousandounces", "тысунций"}:
        return numeric_value, "koz", None
    return numeric_value, raw_unit, None


def normalize_rows(rows: Iterable[MarketDataRow]) -> tuple[list[MarketDataRow], list[str]]:
    normalized: list[MarketDataRow] = []
    warnings: list[str] = []
    units_by_key: dict[tuple[str, str, str], set[str]] = defaultdict(set)

    for row in rows:
        value, unit, warning = normalize_unit_value(row.value, row.unit)
        if warning:
            warnings.append(f"{row.company_or_country} {row.commodity} {row.period}: {warning}")
        normalized_row = row.model_copy(update={"value": value, "unit": unit})
        normalized.append(normalized_row)
        units_by_key[(normalized_row.company_or_country, normalized_row.commodity, normalized_row.metric)].add(unit)

    for (entity, commodity, metric), units in units_by_key.items():
        if len(units) > 1:
            warnings.append(
                f"Mixed units for {entity} / {commodity} / {metric}: {', '.join(sorted(units))}. Values are not merged silently."
            )
    return normalized, warnings


def period_sort_key(period: str) -> tuple[int, str]:
    match = YEAR_RE.search(period)
    year = int(match.group(1)) if match else 0
    return year, period


def latest_rows(rows: Iterable[MarketDataRow]) -> list[MarketDataRow]:
    latest_by_key: dict[tuple[str, str, str], MarketDataRow] = {}
    for row in rows:
        key = (row.company_or_country, row.commodity, row.metric)
        current = latest_by_key.get(key)
        if current is None or period_sort_key(row.period) > period_sort_key(current.period):
            latest_by_key[key] = row
    return sorted(latest_by_key.values(), key=lambda row: (row.company_or_country, row.commodity))
