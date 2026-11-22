"""Patient timeline: filters, search, chronological record list and source inspection."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from modules.search import filter_records
from utils import ui
from utils.data_processing import (ID_COLUMN, build_records, fmt_date, is_missing, raw_record)

PAGE_SIZE = 20
CATEGORY_COLOURS = ["#0F766E", "#12284C", "#5B7DB1", "#7FA7A3", "#8C6D9C", "#B45309", "#4C6A92", "#3B8E83", "#9AA9BD", "#A06A4A", "#6B7A90"]


def render_record_detail(key: str, bundle: dict, records: pd.DataFrame | None = None) -> None:
    """Show one record exactly as stored, what is missing, and the linked source document if there is one."""
    found = raw_record(bundle, key)
    if not found:
        st.warning(f"Record {key} was not found.")
        return
    table, raw = found
    st.markdown(ui.badge("source") + f' <span class="cf-muted">{table} · {key}</span>', unsafe_allow_html=True)
    shown = {k: v for k, v in raw.items() if v is not None}
    st.dataframe(pd.DataFrame({"field": list(shown), "value (as stored)": [str(v) for v in shown.values()]}),
                 hide_index=True, width="stretch")
    if table != "patients":
        from utils.data_processing import missing_fields
        miss = missing_fields(table, raw)
        if miss:
            st.markdown(ui.badge("missing") + " Not recorded in the source: **" + ", ".join(miss) + "**", unsafe_allow_html=True)
    doc_id = raw.get("source_doc_id")
    if table == "documents":
        st.markdown("**Document text**")
        st.code(raw.get("body") or "No text recorded.", language=None)
    elif doc_id:
        d = bundle["documents"]
        hit = d[d["document_id"] == doc_id]
        if not hit.empty:
            h = hit.iloc[0]
            with st.expander(f"Linked source document: {h['title']} ({doc_id}, {fmt_date(h['doc_date'])})"):
                st.code(h["body"] or "No text recorded.", language=None)
    elif table != "patients":
        st.caption("No source document is linked to this record.")


def _encounter_options(bundle: dict) -> dict[str, str | None]:
    opts: dict[str, str | None] = {"All encounters": None}
    for _, e in bundle["encounters"].sort_values("start_date", na_position="last").iterrows():
        reason = e["reason"] if not is_missing(e["reason"]) else "reason not recorded"
        opts[f"{fmt_date(e['start_date'])} · {reason} ({e['encounter_id']})"] = e["encounter_id"]
    return opts


def render(patient: dict, bundle: dict) -> None:
    ui.page_header("Patient Timeline", "Chronological view of all documented records, with search, filters and source inspection.")
    ui.synthetic_banner()
    records = build_records(bundle)
    all_cats = sorted(records["category"].unique())
    default_cats = [c for c in all_cats if c != "Laboratory report"]

    with st.container(border=True):
        c1, c2 = st.columns([2, 1])
        keyword = c1.text_input("Search records", placeholder="e.g. creatinine, discharge, metformin", key="tl_kw",
                                help="Searches titles, details, source and the full text of linked documents.")
        sort = c2.selectbox("Sort", ["Oldest first", "Newest first"], key="tl_sort")
        cats = st.multiselect("Record categories", all_cats, default=default_cats, key=f"tl_cats_{patient['patient_id']}",
                              help="Laboratory report documents are hidden by default because their results already appear as laboratory records.")
        c3, c4, c5 = st.columns(3)
        dated = records["date"].dropna()
        if dated.empty:
            rng = None
            c3.caption("No dated records.")
        else:
            lo, hi = dated.min().date(), dated.max().date()
            rng = c3.date_input("Date range", value=(lo, hi), min_value=lo, max_value=hi, key=f"tl_dates_{patient['patient_id']}")
        enc_opts = _encounter_options(bundle)
        enc_label = c4.selectbox("Encounter", list(enc_opts), key=f"tl_enc_{patient['patient_id']}")
        obs_names = sorted(records["obs_name"].dropna().unique())
        obs_sel = c5.multiselect("Observation", obs_names, key=f"tl_obs_{patient['patient_id']}", help="Limits results to the chosen observations.")
        include_undated = st.checkbox("Include records with no date", value=True, key="tl_undated")

    start = end = None
    if rng:
        if isinstance(rng, (tuple, list)):
            if len(rng) == 2:
                start, end = rng
            elif len(rng) == 1:
                start = rng[0]
        else:
            start = rng
    res = filter_records(records, bundle, categories=cats, start=start, end=end, keyword=keyword, encounter_id=enc_opts[enc_label],
                         observations=obs_sel or None, include_undated=include_undated, newest_first=(sort == "Newest first"))

    n_undated = int(res["date"].isna().sum())
    st.markdown(f"**{len(res)} records** match the current filters" + (f" · {n_undated} without a recorded date" if n_undated else ""))
    if res.empty:
        st.info("No records match the current filters.")
        return

    plot = res.dropna(subset=["date"])
    if not plot.empty:
        fig = px.scatter(plot, x="date", y="category", color="category", hover_name="title",
                         hover_data={"date": "|%d %b %Y", "category": False, "key": True, "source": True},
                         color_discrete_sequence=CATEGORY_COLOURS)
        fig.update_traces(marker=dict(size=9, line=dict(width=1, color="white")))
        fig.update_layout(height=max(240, 60 + 38 * plot["category"].nunique()), showlegend=False, margin=dict(l=0, r=0, t=10, b=0),
                          plot_bgcolor="white", xaxis_title=None, yaxis_title=None)
        fig.update_xaxes(showgrid=True, gridcolor="#EEF2F6")
        st.plotly_chart(fig, width="stretch")
        if n_undated:
            st.caption(f"{n_undated} undated records are listed below but cannot be placed on the chart.")

    pages = max(1, -(-len(res) // PAGE_SIZE))
    page = st.number_input("Page", 1, pages, 1, key="tl_page") if pages > 1 else 1
    chunk = res.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    if pages > 1:
        st.caption(f"Showing records {(page - 1) * PAGE_SIZE + 1}–{min(page * PAGE_SIZE, len(res))} of {len(res)}")

    for _, r in chunk.iterrows():
        label_date = fmt_date(r["date"]) if not pd.isna(r["date"]) else "Date not recorded"
        status = f" [{r['status']}]" if r["status"] else ""
        with st.expander(f"{label_date}  ·  {r['category']}  ·  {r['title']}{status}"):
            badges = ui.badge("source")
            if pd.isna(r["date"]):
                badges += ui.badge("missing", "DATE NOT RECORDED")
            if r["source"] == "Source not recorded":
                badges += ui.badge("missing", "SOURCE NOT RECORDED")
            st.markdown(badges, unsafe_allow_html=True)
            st.markdown(f"**{ui.esc(r['title'])}**")
            st.write(r["details"])
            st.caption(f"Source: {r['source']}")
            render_record_detail(r["key"], bundle, records)
