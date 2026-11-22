"""Overview dashboard for the selected patient."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from modules import data_quality
from utils import ui
from utils.data_processing import age_from_dob, build_records, fmt_date, is_missing, patient_name


def recent_events(records: pd.DataFrame, n: int = 10) -> list[dict]:
    """Most recent dated events. Individual lab/vital results are grouped by date so they don't flood the list."""
    r = records.dropna(subset=["date"])
    ev: list[dict] = []
    other = r[~r["category"].isin(["Laboratory", "Vital sign", "Laboratory report"])]
    for _, x in other.iterrows():
        ev.append(dict(date=x["date"], category=x["category"], text=x["title"], source=x["source"], keys=[x["key"]]))
    for cat in ("Laboratory", "Vital sign"):
        g = r[r["category"] == cat]
        for d, grp in g.groupby("date"):
            ev.append(dict(date=d, category=cat, text=f"{len(grp)} {'laboratory results' if cat == 'Laboratory' else 'vital sign measurements'} recorded",
                           source=", ".join(sorted(set(grp["source"])))[:80], keys=list(grp["key"])))
    ev.sort(key=lambda e: e["date"], reverse=True)
    return ev[:n]


def render(patient: dict, bundle: dict) -> None:
    ui.page_header("Overview", "Documented information for the selected patient.")
    ui.synthetic_banner()
    enc, obs, meds, tasks = bundle["encounters"], bundle["observations"], bundle["medications"], bundle["tasks"]
    age = age_from_dob(patient["birth_date"])
    latest_enc = enc["start_date"].dropna().max() if not enc["start_date"].dropna().empty else None
    labs = obs[obs["category"] == "laboratory"]
    vitals = obs[obs["category"] == "vital-signs"]
    active_meds = meds[meds["status"] == "active"]
    open_tasks = tasks[tasks["status"] == "open"]

    left, right = st.columns([1.1, 2])
    with left:
        dob = fmt_date(patient["birth_date"]) if not is_missing(patient["birth_date"]) else "Not recorded"
        st.markdown(
            f'<div class="cf-card"><div class="cf-metric-label">Patient (synthetic)</div>'
            f'<div style="font-size:1.35rem;font-weight:700;color:{ui.NAVY}">{ui.esc(patient_name(patient))}</div>'
            f'<div class="cf-muted">ID {ui.esc(patient["patient_id"])}</div><hr style="margin:8px 0;border:none;border-top:1px solid #E2E8F0">'
            f'<div><b>Date of birth:</b> {ui.esc(dob)}{f" (age {age})" if age is not None else ""}</div>'
            f'<div><b>Sex:</b> {ui.esc(patient["sex"] or "Not recorded")}</div>'
            f'<div><b>City:</b> {ui.esc(patient["city"] or "Not recorded")}</div>'
            f'<div><b>Language:</b> {ui.esc(patient["language"] or "Not recorded")}</div>'
            f'<div><b>Most recent encounter:</b> {ui.esc(fmt_date(latest_enc) if latest_enc else "No dated encounter recorded")}</div>'
            f'<div style="margin-top:6px">{ui.badge("source")} {ui.badge("alert", "SYNTHETIC")}</div></div>', unsafe_allow_html=True)
    with right:
        c = st.columns(4)
        with c[0]:
            ui.metric_card("Encounters", str(len(enc)), f"{int((enc['enc_class'] == 'inpatient').sum())} inpatient")
        with c[1]:
            ui.metric_card("Laboratory observations", str(len(labs)), f"+ {len(vitals)} vital sign records")
        with c[2]:
            ui.metric_card("Active medication records", str(len(active_meds)), f"{len(meds)} medication records in total")
        with c[3]:
            ui.metric_card("Open documented tasks", str(len(open_tasks)), f"{len(tasks)} tasks documented")
        st.caption("Counts are taken directly from the records (DERIVED). 'Active' means the record status is 'active' in the source.")

    col_a, col_b = st.columns([1.4, 1])
    records = build_records(bundle)
    with col_a:
        st.markdown("#### Recent clinical events")
        events = recent_events(records, 10)
        if not events:
            st.info("No dated events recorded.")
        for e in events:
            st.markdown(f'<div class="cf-event"><div class="cf-event-date">{fmt_date(e["date"])} · {ui.esc(e["category"])}</div>'
                        f'<div class="cf-rec-title">{ui.esc(e["text"])}</div></div>', unsafe_allow_html=True)
        st.caption("Open the Patient Timeline for every record and its source.")
    with col_b:
        st.markdown("#### Information quality indicators")
        st.caption("Documentation checks, not clinical alerts.")
        findings = data_quality.audit(bundle, date.today(), include_mapping=False)
        summ = data_quality.summarise(findings)
        shown = summ[summ["count"] > 0]
        if shown.empty:
            st.markdown(ui.badge("source", "NO FINDINGS") + " under the implemented checks.", unsafe_allow_html=True)
        for _, r in shown.iterrows():
            st.markdown(f'<div class="cf-card" style="padding:8px 12px;margin-bottom:6px"><b>{r["count"]}</b> · {ui.esc(r["check"])}</div>', unsafe_allow_html=True)
        st.caption("Details and export: Data & Interoperability → Data quality audit.")
