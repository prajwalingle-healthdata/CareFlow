"""Information quality and data audit.

Findings describe the *documentation* (missing, inconsistent or possibly outdated entries). They are
not clinical diagnoses or safety alerts. Source data is never modified: normalisation is shown
alongside the original text in a transformation log.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from utils import fhir_mapping
from utils.data_processing import (EXPECTED_FIELDS, ID_COLUMN, fmt_date, is_missing, norm_key,
                                   normalisation_log, patient_name)
from utils import ui

FINDING_COLUMNS = ["check", "severity", "table", "record_id", "field", "message"]
CHECKS = ["Missing date", "Missing value", "Missing unit", "Missing source", "Duplicate record",
          "Conflicting entries", "Inconsistent terminology", "Incomplete medication information",
          "Potentially outdated medication record", "Not fully mappable to FHIR"]
OUTDATED_MONTHS = 12


def _f(check, sev, table, rid, field, msg):
    return dict(check=check, severity=sev, table=table, record_id=rid, field=field, message=msg)


def audit(bundle: dict[str, pd.DataFrame], as_of: date | None = None, include_mapping: bool = True) -> pd.DataFrame:
    """Run all checks on one patient's records. Returns one row per finding."""
    as_of = as_of or date.today()
    out: list[dict] = []
    date_fields = {"encounters": "start_date", "conditions": "onset_date", "observations": "effective_date",
                   "medications": "start_date", "procedures": "performed_date", "documents": "doc_date"}

    # missing dates / source
    for table, field in date_fields.items():
        for _, r in bundle[table].iterrows():
            rid = r[ID_COLUMN[table]]
            if is_missing(r[field]):
                out.append(_f("Missing date", "review", table, rid, field, f"{field} is not recorded."))
    for table in ("encounters", "conditions", "observations", "medications", "procedures", "documents", "tasks"):
        for _, r in bundle[table].iterrows():
            if is_missing(r["source_system"]) and is_missing(r.get("source_doc_id")):
                out.append(_f("Missing source", "review", table, r[ID_COLUMN[table]], "source_system", "No source system or source document is recorded."))

    # missing values / units
    for _, r in bundle["observations"].iterrows():
        if is_missing(r["value_num"]) and is_missing(r["value_text"]):
            out.append(_f("Missing value", "review", "observations", r["observation_id"], "value_num", f"{r['display']}: no value recorded (status: {r['status']})."))
        elif not is_missing(r["value_num"]) and is_missing(r["unit"]):
            out.append(_f("Missing unit", "review", "observations", r["observation_id"], "unit", f"{r['display']}: numeric value recorded without a unit."))

    # incomplete medication information + potentially outdated
    for _, m in bundle["medications"].iterrows():
        miss = [f for f in ("dose", "route", "frequency") if is_missing(m[f])]
        if miss:
            out.append(_f("Incomplete medication information", "review", "medications", m["medication_id"], ", ".join(miss), f"{m['name']}: {', '.join(miss)} not recorded."))
        if m["status"] == "active":
            if not is_missing(m["end_date"]) and pd.to_datetime(m["end_date"]).date() < as_of:
                out.append(_f("Potentially outdated medication record", "review", "medications", m["medication_id"], "end_date",
                              f"{m['name']}: status is 'active' but the recorded end date ({fmt_date(m['end_date'])}) has passed."))
            if is_missing(m["last_reviewed"]):
                out.append(_f("Potentially outdated medication record", "info", "medications", m["medication_id"], "last_reviewed",
                              f"{m['name']}: active record with no review date recorded."))
            else:
                months = (pd.Timestamp(as_of) - pd.to_datetime(m["last_reviewed"])).days / 30.44
                if months > OUTDATED_MONTHS:
                    out.append(_f("Potentially outdated medication record", "review", "medications", m["medication_id"], "last_reviewed",
                                  f"{m['name']}: active record last reviewed {fmt_date(m['last_reviewed'])} (over {OUTDATED_MONTHS} months before today)."))

    # duplicates
    def dupes(df, subset, table, label):
        d = df[df.duplicated(subset=subset, keep=False)]
        for _, grp in d.groupby(subset, dropna=False):
            ids = list(grp[ID_COLUMN[table]])
            for i in ids[1:]:
                out.append(_f("Duplicate record", "review", table, i, "", f"{label} duplicates {ids[0]} (same {', '.join(subset)})."))
    obs = bundle["observations"]
    dupes(obs, ["code", "effective_date", "value_num", "unit", "source_system"], "observations", "Observation")
    dupes(bundle["conditions"], ["display", "onset_date"], "conditions", "Condition")
    dupes(bundle["medications"], ["name", "dose", "frequency", "start_date", "status"], "medications", "Medication")
    dupes(bundle["encounters"], ["start_date", "reason"], "encounters", "Encounter")

    # conflicts
    for (code, d), grp in obs.dropna(subset=["effective_date"]).groupby(["code", "effective_date"]):
        vals = grp["value_num"].dropna().unique()
        if len(vals) > 1:
            out.append(_f("Conflicting entries", "review", "observations", ", ".join(grp["observation_id"]), "value_num",
                          f"{grp.iloc[0]['display']} has different values on {fmt_date(d)}: {', '.join(f'{v:g}' for v in vals)}."))
    meds = bundle["medications"].copy()
    meds["_k"] = meds["name"].map(norm_key)
    for k, grp in meds.groupby("_k"):
        act_rows = grp[grp["status"] == "active"]
        stop_rows = grp[grp["status"] == "stopped"]
        overlap = False
        for _, a in act_rows.iterrows():
            for _, s_ in stop_rows.iterrows():
                # sequential records (stopped on/before the active one started) are a normal dose change, not a conflict
                if is_missing(a["start_date"]) or is_missing(s_["end_date"]) or pd.to_datetime(a["start_date"]) < pd.to_datetime(s_["end_date"]):
                    overlap = True
        if overlap:
            out.append(_f("Conflicting entries", "review", "medications", ", ".join(grp["medication_id"]), "status",
                          f"{grp.iloc[0]['name']} appears as both active and stopped, with overlapping or unclear dates."))
        act = grp[grp["status"] == "active"]
        if len(act) > 1 and act["dose"].nunique(dropna=True) > 1:
            out.append(_f("Conflicting entries", "review", "medications", ", ".join(act["medication_id"]), "dose",
                          f"{act.iloc[0]['name']}: more than one active record with different doses ({', '.join(act['dose'].dropna())})."))

    # inconsistent terminology / units
    conds = bundle["conditions"].copy()
    conds["_k"] = conds["display"].map(norm_key)
    for k, grp in conds.groupby("_k"):
        if grp["display"].str.lower().nunique() > 1:
            out.append(_f("Inconsistent terminology", "info", "conditions", ", ".join(grp["condition_id"]), "display",
                          f"Different wording for what may be the same condition: {', '.join(sorted(set(grp['display'])))}."))
    for k, grp in meds.groupby("_k"):
        if grp["name"].str.lower().nunique() > 1:
            out.append(_f("Inconsistent terminology", "info", "medications", ", ".join(grp["medication_id"]), "name",
                          f"Different names for what may be the same medication: {', '.join(sorted(set(grp['name'])))}."))
    for (code, disp), grp in obs.dropna(subset=["unit"]).groupby(["code", "display"]):
        if grp["unit"].nunique() > 1:
            out.append(_f("Inconsistent terminology", "review", "observations", ", ".join(grp["observation_id"]), "unit",
                          f"{disp} recorded in more than one unit ({', '.join(sorted(grp['unit'].unique()))}); values are not converted."))

    # FHIR mapping limitations
    for item in (fhir_mapping.build_resources(bundle) if include_mapping else []):
        if item["table"] == "tasks":
            continue
        issues = [i for i in item["issues"] if not i.startswith(("Report status", "Document status", "Author held", "Medication held", "Intent not recorded",
                                                                  "Report type held", "Reason held", "Dosage held"))]
        if issues:
            out.append(_f("Not fully mappable to FHIR", "info", item["table"], item["record_id"], "", " ".join(issues)))

    df = pd.DataFrame(out, columns=FINDING_COLUMNS)
    return df


def summarise(findings: pd.DataFrame) -> pd.DataFrame:
    if findings.empty:
        return pd.DataFrame({"check": CHECKS, "count": 0})
    s = findings.groupby("check").size().reindex(CHECKS, fill_value=0)
    return s.rename("count").reset_index()


def quality_score_note(bundle) -> str:
    n = sum(len(bundle[t]) for t in ("encounters", "conditions", "observations", "medications", "procedures", "documents", "tasks"))
    return f"{n} clinical records examined"


def report_markdown(patient: dict, findings: pd.DataFrame, bundle: dict) -> str:
    lines = [f"# CareFlow data quality report", "",
             "SYNTHETIC DATA - fictional patient. Findings describe documentation gaps and inconsistencies, not clinical conditions.", "",
             f"Patient: {patient_name(patient)} ({patient['patient_id']})",
             f"Generated: {date.today().isoformat()} by the rule-based CareFlow audit (GENERATED content)",
             f"Scope: {quality_score_note(bundle)}", "", "## Summary by check", ""]
    for _, r in summarise(findings).iterrows():
        lines.append(f"- {r['check']}: {r['count']}")
    lines += ["", "## Findings", ""]
    if findings.empty:
        lines.append("No findings.")
    for _, r in findings.iterrows():
        lines.append(f"- [{r['check']}] {r['table']} {r['record_id']}: {r['message']}")
    nlog = normalisation_log(bundle)
    lines += ["", "## Normalisation log (original source text is preserved in the database)", ""]
    if nlog.empty:
        lines.append("No normalisation applied.")
    for _, r in nlog.iterrows():
        lines.append(f"- {r['record_id']} {r['field']}: '{r['original_source_text']}' -> '{r['normalised_text']}'")
    lines += ["", "Limitations: checks are rule-based and illustrative; the synonym list is small; no clinical validation has been performed."]
    return "\n".join(lines)


# ---- UI -------------------------------------------------------------------------------------------
def render_audit(patient: dict, bundle: dict) -> None:
    findings = audit(bundle)
    ui.layer_legend()
    st.markdown("Findings below describe **documentation quality** (missing, inconsistent or possibly outdated entries). "
                "They are **not** diagnoses or definitive safety alerts.")
    summ = summarise(findings)
    cols = st.columns(5)
    for i, (_, r) in enumerate(summ.iterrows()):
        with cols[i % 5]:
            ui.metric_card(r["check"], str(r["count"]), None)
    st.markdown("#### Findings")
    if findings.empty:
        st.success("No documentation findings for this patient under the implemented checks.")
    else:
        pick = st.multiselect("Filter by check", CHECKS, default=[c for c in CHECKS if (findings["check"] == c).any()], key="dq_filter")
        st.dataframe(findings[findings["check"].isin(pick)].rename(columns={"record_id": "record id(s)"}), width="stretch", hide_index=True)
    st.markdown("#### Normalisation log")
    st.caption("NORMALISED layer: original wording is kept and mapped to a common term. Source rows in the database are unchanged.")
    nlog = normalisation_log(bundle)
    if nlog.empty:
        st.info("No terms were normalised for this patient.")
    else:
        st.dataframe(nlog, width="stretch", hide_index=True)
    st.markdown("#### Export")
    md = report_markdown(patient, findings, bundle)
    c1, c2 = st.columns(2)
    c1.download_button("Download report (.md)", md, file_name=f"careflow_data_quality_{patient['patient_id']}.md", mime="text/markdown")
    c2.download_button("Download findings (.csv)", findings.to_csv(index=False), file_name=f"careflow_findings_{patient['patient_id']}.csv", mime="text/csv")
    with st.expander("Preview report"):
        st.markdown(md)
