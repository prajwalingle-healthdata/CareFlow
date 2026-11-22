"""CareFlow - Clinical Timeline & Handover Intelligence (educational prototype, synthetic data only).

Run with:   streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from database import database as db
from modules import about, analytics, dashboard, handover, interoperability, summarisation, timeline
from utils import ui
from utils.data_processing import age_from_dob, patient_name

st.set_page_config(page_title="CareFlow", page_icon=":material/monitor_heart:", layout="wide", initial_sidebar_state="expanded")
ui.inject_css()
db.init_db()

PAGES = {
    "Overview": ":material/dashboard: Overview",
    "Patient Timeline": ":material/timeline: Patient Timeline",
    "Clinical Trends": ":material/show_chart: Clinical Trends",
    "Clinical Summary": ":material/summarize: Clinical Summary",
    "Handover Builder": ":material/assignment: Handover Builder",
    "Data & Interoperability": ":material/hub: Data & Interoperability",
    "About CareFlow": ":material/info: About CareFlow",
}


def reset_demo() -> None:
    counts = db.reset_database()
    for k in [k for k in st.session_state if k.startswith(("ho_", "tl_", "tr_", "sum_", "io_", "dq_"))]:
        del st.session_state[k]
    st.session_state["reset_msg"] = f"Dataset regenerated: {counts['patients']} patients, {sum(counts.values()) - counts['patients']} records."


with st.sidebar:
    st.markdown('<p class="cf-brand">Care<span>Flow</span></p><div class="cf-tag">Clinical Timeline &amp; Handover Intelligence</div>', unsafe_allow_html=True)
    page = st.radio("Navigation", list(PAGES), format_func=PAGES.get, label_visibility="collapsed", key="nav")
    st.divider()
    patients = db.list_patients()
    ids = list(patients["patient_id"])
    labels = {r["patient_id"]: f"{patient_name(r)} · {r['patient_id']}" for _, r in patients.iterrows()}
    pid = st.selectbox("Synthetic patient", ids, format_func=labels.get, key="patient_id")
    st.caption("All patients are fictional.")
    st.divider()
    st.markdown("**Label key**")
    ui.layer_legend()
    st.divider()
    st.button("Reset demonstration dataset", key="reset_btn", on_click=reset_demo, help="Deletes and regenerates the local SQLite database from the synthetic generator and clears your edits.")
    if "reset_msg" in st.session_state:
        st.success(st.session_state["reset_msg"])
    st.caption("Prototype · synthetic data · not clinically validated")

bundle = db.load_patient_bundle(pid)
patient = bundle["patients"].iloc[0].to_dict()

if page == "Overview":
    dashboard.render(patient, bundle)
elif page == "Patient Timeline":
    timeline.render(patient, bundle)
elif page == "Clinical Trends":
    analytics.render(patient, bundle)
elif page == "Clinical Summary":
    summarisation.render(patient, bundle)
elif page == "Handover Builder":
    handover.render(patient, bundle)
elif page == "Data & Interoperability":
    interoperability.render(patient, bundle)
else:
    about.render()

st.divider()
st.caption(ui.DISCLAIMER)
