from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd


def flatten_chart_columns(columns: Any) -> list[str]:
    if isinstance(columns, pd.MultiIndex):
        flattened: list[str] = []
        for column in columns.to_flat_index():
            parts = [str(part) for part in column if part not in (None, "")]
            flattened.append(" · ".join(parts) or "value")
        return flattened
    return [str(column) for column in columns]


def prepare_market_chart_df(
    rows: Sequence[dict[str, Any]],
    *,
    index: str,
    columns: str | Sequence[str],
    value: str = "value",
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    column_list = [columns] if isinstance(columns, str) else list(columns)
    required = [index, value, *column_list]
    df = pd.DataFrame(rows)
    if any(column not in df.columns for column in required):
        return pd.DataFrame()

    df[value] = pd.to_numeric(df[value], errors="coerce")
    df = df.dropna(subset=[value])
    if df.empty:
        return pd.DataFrame()

    chart_df = df.pivot_table(index=index, columns=column_list, values=value, aggfunc="first")
    if chart_df.empty:
        return pd.DataFrame()

    chart_df.columns = flatten_chart_columns(chart_df.columns)
    chart_df.columns = [str(column) for column in chart_df.columns]
    chart_df.index = chart_df.index.map(str)
    chart_df = chart_df.sort_index()
    return chart_df
