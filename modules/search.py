"""Search and filter logic over a patient's unified record view (pure functions, easy to test)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from utils.data_processing import is_missing


def filter_records(records: pd.DataFrame, bundle: dict[str, pd.DataFrame], *, categories: list[str] | None = None,
                   start: date | None = None, end: date | None = None, keyword: str = "",
                   encounter_id: str | None = None, observations: list[str] | None = None,
                   include_undated: bool = True, newest_first: bool = False) -> pd.DataFrame:
    df = records.copy()
    if categories is not None:
        df = df[df["category"].isin(categories)]
    if start is not None or end is not None:
        dated = df["date"].notna()
        keep = pd.Series(True, index=df.index)
        if start is not None:
            keep &= df["date"] >= pd.Timestamp(start)
        if end is not None:
            keep &= df["date"] <= pd.Timestamp(end)
        df = df[(dated & keep) | (~dated & include_undated)]
    elif not include_undated:
        df = df[df["date"].notna()]
    if encounter_id:
        df = df[(df["encounter_id"] == encounter_id) | (df["key"] == encounter_id)]
    if observations:
        df = df[df["obs_name"].isin(observations)]
    kw = keyword.strip().lower()
    if kw:
        # search the visible text and the underlying source row, including linked document text
        def haystack(row) -> str:
            parts = [row["title"], row["details"], row["category"], row["source"], str(row["status"] or "")]
            tbl = bundle.get(row["table"])
            if tbl is not None:
                idcol = tbl.columns[0]
                hit = tbl[tbl[idcol] == row["key"]]
                if not hit.empty:
                    parts += [str(v) for v in hit.iloc[0].tolist() if not is_missing(v)]
            return " ".join(parts).lower()
        df = df[df.apply(lambda r: kw in haystack(r), axis=1)]
    return df.sort_values("date", ascending=not newest_first, na_position="last", kind="stable")
