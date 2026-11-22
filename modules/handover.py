"""Handover builder.

Builds an editable DRAFT from documented records that the clinician selects. The text is assembled
by fixed templates from stored fields only. It never recommends treatment, never labels a patient as
stable/unstable, never assigns urgency or severity, and always carries a verification warning.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from modules import data_quality
from utils import ui
from utils.data_processing import (age_from_dob, build_records, fmt_date, fmt_num, is_missing, patient_name,
                                   ref_range_str, value_str)

SECTION_TITLES = ["PATIENT IDENTIFIER", "PATIENT DEMOGRAPHICS", "REASON FOR MOST RECENT DOCUMENTED ENCOUNTER",
                  "RELEVANT DOCUMENTED MEDICAL HISTORY", "RECENT CLINICAL EVENTS", "DOCUMENTED DIAGNOSES AND CONDITIONS",
                  "RECORDED MEDICATIONS", "RELEVANT LABORATORY AND OBSERVATION RESULTS", "OUTSTANDING INVESTIGATIONS (AS DOCUMENTED)",
                  "DOCUMENTED FOLLOW-UP PLANS", "INFORMATION MISSING OR REQUIRING VERIFICATION", "SOURCES USED"]


# ---- candidate records ----------------------------------------------------------------------------
def candidates(bundle: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Records the clinician can include or exclude, with sensible default selections."""
    rows = []
    enc = bundle["encounters"].copy()
    dated = enc.dropna(subset=["start_date"]).sort_values("start_date")
    latest_id = dated.iloc[-1]["encounter_id"] if not dated.empty else None
    for _, e in enc.sort_values("start_date", na_position="last").iterrows():
        rows.append(dict(Include=(e["encounter_id"] == latest_id or e["enc_class"] == "inpatient"), Category="Encounter", Date=fmt_date(e["start_date"]),
                         Record=e["reason"] if not is_missing(e["reason"]) else "Reason not recorded", ID=e["encounter_id"], _sort=e["start_date"] or ""))
    for _, c in bundle["conditions"].iterrows():
        rows.append(dict(Include=True, Category="Condition", Date=fmt_date(c["onset_date"]), Record=f"{c['display']} ({c['clinical_status']})", ID=c["condition_id"], _sort=c["onset_date"] or ""))
    for _, m in bundle["medications"].iterrows():
        rows.append(dict(Include=(m["status"] == "active"), Category="Medication", Date=fmt_date(m["start_date"]), Record=f"{m['name']} ({m['status']})", ID=m["medication_id"], _sort=m["start_date"] or ""))
    obs = bundle["observations"].copy()
    obs["_d"] = pd.to_datetime(obs["effective_date"], errors="coerce")
    latest_per = obs.dropna(subset=["_d", "value_num"]).sort_values("_d").groupby("display").tail(1)["observation_id"].tolist()
    for _, o in obs.sort_values("_d", na_position="last").iterrows():
        rows.append(dict(Include=o["observation_id"] in latest_per, Category="Observation", Date=fmt_date(o["effective_date"]), Record=f"{o['display']}: {value_str(o)}", ID=o["observation_id"], _sort=o["effective_date"] or ""))
    for _, p in bundle["procedures"].iterrows():
        rows.append(dict(Include=True, Category="Procedure", Date=fmt_date(p["performed_date"]), Record=p["display"], ID=p["procedure_id"], _sort=p["performed_date"] or ""))
    for _, t in bundle["tasks"].iterrows():
        rows.append(dict(Include=(t["status"] != "completed"), Category="Follow-up task", Date=fmt_date(t["documented_date"]), Record=f"{t['description']} ({t['status'] if not is_missing(t['status']) else 'status not recorded'})", ID=t["task_id"], _sort=t["documented_date"] or ""))
    df = pd.DataFrame(rows)
    order = {"Encounter": 0, "Condition": 1, "Medication": 2, "Observation": 3, "Procedure": 4, "Follow-up task": 5}
    df["_o"] = df["Category"].map(order)
    return df.sort_values(["_o", "_sort"], kind="stable").drop(columns=["_o", "_sort"]).reset_index(drop=True)


# ---- draft text -----------------------------------------------------------------------------------
def _src(row, key) -> str:
    return f"[{row[key]}]"


def build_handover(bundle: dict[str, pd.DataFrame], include_ids: set[str], as_of: date | None = None) -> tuple[str, list[str]]:
    as_of = as_of or date.today()
    p = bundle["patients"].iloc[0]
    used: list[str] = [p["patient_id"]]
    sec: dict[int, list[str]] = {i: [] for i in range(1, 13)}
    ev5: list[tuple[str, str]] = []   # (ISO date or '', line) so recent events can be sorted newest first

    # 1-2
    sec[1].append(f"{p['patient_id']} (synthetic patient) - {patient_name(p)}")
    age = age_from_dob(p["birth_date"], as_of)
    sec[2].append(f"Sex: {p['sex'] or 'not recorded'}")
    sec[2].append(f"Date of birth: {fmt_date(p['birth_date'])}" + (f" (age {age})" if age is not None else ""))

    # 3 and 5: encounters
    enc = bundle["encounters"]
    enc_sel = enc[enc["encounter_id"].isin(include_ids)].copy()
    dated = enc_sel.dropna(subset=["start_date"]).sort_values("start_date")
    if dated.empty:
        sec[3].append("No dated encounter selected for inclusion.")
    else:
        e = dated.iloc[-1]
        used.append(e["encounter_id"])
        line = (f"{fmt_date(e['start_date'])}: {e['enc_class']} encounter, {e['department'] or 'department not recorded'}. "
                f"Reason as recorded: {e['reason'] if not is_missing(e['reason']) else 'not recorded'}. Status recorded: {e['status'] or 'not recorded'}.")
        if not is_missing(e["disposition"]):
            line += f" Disposition recorded: {e['disposition']}."
        sec[3].append(line + f" [{e['encounter_id']}]")
        if not is_missing(e["source_doc_id"]):
            used.append(e["source_doc_id"])
        earlier = dated.iloc[:-1]
        for _, x in earlier.sort_values("start_date", ascending=False).iterrows():
            used.append(x["encounter_id"])
            ev5.append((x["start_date"], f"{fmt_date(x['start_date'])}: {x['enc_class']} encounter - {x['reason']} [{x['encounter_id']}]"))
    for _, x in enc_sel[enc_sel["start_date"].isna()].iterrows():
        used.append(x["encounter_id"])
        ev5.append(("", f"Date not recorded: {x['enc_class']} encounter - {x['reason']} [{x['encounter_id']}]"))

    # 4 and 6: conditions
    cond = bundle["conditions"]
    csel = cond[cond["condition_id"].isin(include_ids)]
    first = pd.to_datetime(enc["start_date"].dropna()).min() if not enc["start_date"].dropna().empty else None
    for _, c in csel.iterrows():
        used.append(c["condition_id"])
        ver = "" if c["verification_status"] in ("confirmed", None) else f"; verification: {c['verification_status']}"
        onset = f"onset {fmt_date(c['onset_date'])}" if not is_missing(c["onset_date"]) else "onset date not recorded"
        sec[6].append(f"{c['display']} - status: {c['clinical_status'] or 'not recorded'}; {onset}{ver} [{c['condition_id']}]")
        o = pd.to_datetime(c["onset_date"]) if not is_missing(c["onset_date"]) else None
        if c["clinical_status"] in ("resolved", "inactive") or (first is not None and o is not None and o < first):
            sec[4].append(f"{c['display']} ({onset}; status {c['clinical_status']}) [{c['condition_id']}]")

    # 5: procedures
    proc = bundle["procedures"]
    for _, r in proc[proc["procedure_id"].isin(include_ids)].sort_values("performed_date", ascending=False, na_position="last").iterrows():
        used.append(r["procedure_id"])
        ev5.append((r["performed_date"] or "", f"{fmt_date(r['performed_date'])}: procedure - {r['display']} (status {r['status']}) [{r['procedure_id']}]"))

    sec[5] = [line for _, line in sorted(ev5, key=lambda t: t[0], reverse=True)]

    # 7: medications
    med = bundle["medications"]
    for _, m in med[med["medication_id"].isin(include_ids)].iterrows():
        used.append(m["medication_id"])
        parts = [str(m[k]) for k in ("dose", "route", "frequency") if not is_missing(m[k])]
        dose = " ".join(parts) if parts else "dose details not recorded"
        extra = f"; start {fmt_date(m['start_date'])}" if not is_missing(m["start_date"]) else "; start date not recorded"
        if not is_missing(m["end_date"]):
            extra += f"; end {fmt_date(m['end_date'])}"
        sec[7].append(f"{m['name']} - {dose}; status: {m['status']}{extra} [{m['medication_id']}]")

    # 8: observations
    obs = bundle["observations"]
    osel = obs[obs["observation_id"].isin(include_ids)].copy()
    osel["_d"] = pd.to_datetime(osel["effective_date"], errors="coerce")
    for name, g in osel.groupby("display"):
        for _, o in g.sort_values("_d", ascending=False, na_position="last").iterrows():
            used.append(o["observation_id"])
            if not is_missing(o["source_doc_id"]):
                used.append(o["source_doc_id"])
            extra = []
            rr = ref_range_str(o)
            if rr:
                extra.append(f"source reference range {rr}")
            if not is_missing(o["flag"]):
                extra.append(f"flag supplied by source: {o['flag']}")
            tail = f" ({'; '.join(extra)})" if extra else " (no reference range in source)"
            sec[8].append(f"{name}: {value_str(o)} on {fmt_date(o['effective_date'])}{tail} [{o['observation_id']}]")

    # 9-10: tasks
    tasks = bundle["tasks"]
    for _, t in tasks[tasks["task_id"].isin(include_ids)].iterrows():
        used.append(t["task_id"])
        status = t["status"] if not is_missing(t["status"]) else "status not recorded"
        due = f"due {fmt_date(t['due_date'])}" if not is_missing(t["due_date"]) else "due date not recorded"
        line = f"{t['description']} - {status}; {due}; documented {fmt_date(t['documented_date'])} [{t['task_id']}]"
        if status == "open" and not is_missing(t["due_date"]) and pd.to_datetime(t["due_date"]).date() < as_of:
            line += " - due date has passed; no completion documented in available records"
        (sec[9] if t["task_type"] == "investigation" and status != "completed" else sec[10]).append(line)

    # 11: missing / verification
    findings = data_quality.audit(bundle, as_of, include_mapping=False)
    included_all = set(include_ids) | {p["patient_id"]}
    for _, f in findings.iterrows():
        ids = {x.strip() for x in str(f["record_id"]).split(",")}
        if ids & included_all:
            sec[11].append(f"{f['check']}: {f['message']} [{f['record_id']}]")
    cand = candidates(bundle)
    excluded = cand[~cand["ID"].isin(include_ids)]
    if len(excluded):
        sec[11].append(f"{len(excluded)} documented record(s) were excluded from this draft by the author ({', '.join(sorted(excluded['Category'].unique()))}); they are still in the full record.")
    sec[11].append("Follow-up plans written as free text in notes or discharge summaries are not extracted by this draft; check the linked documents.")
    sec[11].append("All content must be checked against the original records before use.")

    # 12: sources
    seen: dict[str, None] = dict.fromkeys(used)
    docs = bundle["documents"].set_index("document_id")
    for k in seen:
        if k.startswith("DOC-") and k in docs.index:
            d = docs.loc[k]
            sec[12].append(f"{k}: {d['doc_type']} - {d['title']} ({fmt_date(d['doc_date'])}; {d['source_system'] if not is_missing(d['source_system']) else 'source system not recorded'})")
    n_rec = len([k for k in seen if not k.startswith("DOC-")])
    sec[12].append(f"{n_rec} structured record(s) from the CareFlow synthetic database (ids shown in square brackets above).")

    out = ["CAREFLOW HANDOVER DRAFT - SYNTHETIC DATA", "=" * 44,
           f"DRAFT generated {as_of.isoformat()} by the CareFlow rule-based draft builder. Not verified clinical documentation.",
           ui.DRAFT_WARNING, ""]
    for i, title in enumerate(SECTION_TITLES, start=1):
        out.append(f"{i}. {title}")
        lines = sec[i]
        if not lines:
            lines = ["None selected or none documented."]
        out += [f"   - {ln}" for ln in lines]
        out.append("")
    out += ["VERIFICATION (to be completed by a clinician)", "   [ ] Original records reviewed   [ ] Content checked for accuracy   [ ] Completeness confirmed",
            "   Reviewed by: ____________________   Date/time: ____________________"]
    return "\n".join(out), list(seen)


# ---- UI -------------------------------------------------------------------------------------------
def render(patient: dict, bundle: dict) -> None:
    pid = patient["patient_id"]
    ui.page_header("Handover Builder", "Prepare an editable handover draft from documented records you choose.")
    ui.synthetic_banner()
    ui.draft_banner()
    ver_key, text_key = f"ho_ver_{pid}", f"ho_text_{pid}"
    st.session_state.setdefault(ver_key, 0)
    cand = candidates(bundle)

    tab1, tab2, tab3 = st.tabs(["1 · Select records", "2 · Edit draft", "3 · Preview, copy and export"])
    with tab1:
        st.markdown("Tick the records to include. Defaults: the most recent encounter and inpatient stays, all conditions, active medications, "
                    "the latest value of each observation, all procedures and tasks that are not completed. Nothing is chosen by clinical significance.")
        cats = st.multiselect("Show categories", sorted(cand["Category"].unique()), default=sorted(cand["Category"].unique()), key=f"ho_cats_{pid}")
        view = cand[cand["Category"].isin(cats)]
        edited = st.data_editor(view, hide_index=True, width="stretch", height=420,
                                disabled=["Category", "Date", "Record", "ID"], key=f"ho_editor_{pid}_{st.session_state[ver_key]}",
                                column_config={"Include": st.column_config.CheckboxColumn("Include", default=True)})
        hidden = cand[~cand["Category"].isin(cats)]
        include_ids = set(edited.loc[edited["Include"], "ID"]) | set(hidden.loc[hidden["Include"], "ID"])
        c1, c2 = st.columns([1, 1])
        c1.markdown(f"**{len(include_ids)}** records selected.")
        if c2.button("Reset selection to defaults", key=f"ho_resetsel_{pid}"):
            st.session_state[ver_key] += 1
            st.rerun()

        def _generate() -> None:
            text, _ = build_handover(bundle, include_ids)
            st.session_state[text_key] = text
            st.session_state[f"ho_edit_{pid}"] = text
        st.button("Generate handover draft", type="primary", on_click=_generate, key=f"ho_gen_{pid}")
        if text_key in st.session_state:
            st.success("Draft generated. Continue to the 'Edit draft' tab.")

    with tab2:
        if text_key not in st.session_state:
            st.info("Select records and generate a draft first.")
        else:
            st.markdown(ui.badge("generated") + " Edit freely. Your edits are kept until you generate a new draft or reset the dataset.", unsafe_allow_html=True)
            st.text_area("Handover draft", key=f"ho_edit_{pid}", height=520)

    with tab3:
        if text_key not in st.session_state:
            st.info("Generate a draft first.")
        else:
            text = st.session_state.get(f"ho_edit_{pid}", st.session_state[text_key])
            ui.draft_banner()
            st.markdown("**Copy:** use the copy icon at the top right of the box below.")
            st.code(text, language=None)
            d1, d2 = st.columns(2)
            d1.download_button("Download as text (.txt)", text, file_name=f"careflow_handover_draft_{pid}.txt", mime="text/plain")
            d2.download_button("Download as Markdown (.md)", "```\n" + text + "\n```", file_name=f"careflow_handover_draft_{pid}.md", mime="text/markdown")
            st.caption("PDF export is not included in this prototype (it would add a PDF library dependency). The .txt file can be printed or pasted into a document.")
