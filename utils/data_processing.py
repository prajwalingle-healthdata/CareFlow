"""Shared data helpers: formatting, the unified record view used by the timeline, and term normalisation.

Data layers used by CareFlow (and labelled as such in the UI):
  SOURCE      - values exactly as stored in the database (never modified)
  NORMALISED  - original text mapped to a common term (original always kept next to it)
  DERIVED     - computed from source values (counts, first/latest/min/max)
  GENERATED   - text produced by the rule-based summary / handover engines
"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd

# Which fields we expect to be present on each table. Used for "not recorded" display and data quality.
EXPECTED_FIELDS = {
    "encounters": ["start_date", "reason", "source_system"],
    "conditions": ["onset_date", "clinical_status", "source_system"],
    "observations": ["effective_date", "value_num", "unit", "source_system"],
    "medications": ["dose", "route", "frequency", "start_date", "source_system"],
    "procedures": ["performed_date", "source_system"],
    "documents": ["doc_date", "author_role", "source_system"],
    "tasks": ["due_date", "status", "source_system"],
}
ID_COLUMN = {"patients": "patient_id", "encounters": "encounter_id", "conditions": "condition_id",
             "observations": "observation_id", "medications": "medication_id", "procedures": "procedure_id",
             "documents": "document_id", "tasks": "task_id"}
PREFIX_TABLE = {"SYN": "patients", "ENC": "encounters", "CON": "conditions", "OBS": "observations",
                "MED": "medications", "PRO": "procedures", "DOC": "documents", "TSK": "tasks"}

# Illustrative synonym rules for normalisation (original text is always preserved).
TERM_RULES = {
    "htn": "Hypertension", "high blood pressure": "Hypertension",
    "type 2 dm": "Type 2 diabetes mellitus", "t2dm": "Type 2 diabetes mellitus",
    "type 2 diabetes": "Type 2 diabetes mellitus",
    "ventolin": "Salbutamol", "glucophage": "Metformin",
}


def is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() == "")


def fmt_date(v, fmt: str = "%d %b %Y") -> str:
    if is_missing(v):
        return "Date not recorded"
    try:
        return pd.to_datetime(v).strftime(fmt).lstrip("0")
    except Exception:
        return str(v)


def fmt_num(v) -> str:
    return f"{v:g}" if not is_missing(v) else ""


def age_from_dob(dob: str, as_of: date | None = None) -> int | None:
    if is_missing(dob):
        return None
    as_of = as_of or date.today()
    b = datetime.strptime(dob, "%Y-%m-%d").date()
    return as_of.year - b.year - ((as_of.month, as_of.day) < (b.month, b.day))


def patient_name(p) -> str:
    return f"{p['given_name']} {p['family_name']}"


def value_str(row) -> str:
    """Observation value with unit, or an explicit 'not recorded' marker."""
    if not is_missing(row.get("value_num")):
        unit = row.get("unit")
        return f"{fmt_num(row['value_num'])} {unit}".strip() if not is_missing(unit) else f"{fmt_num(row['value_num'])} (unit not recorded)"
    if not is_missing(row.get("value_text")):
        return str(row["value_text"])
    return "value not recorded"


def ref_range_str(row) -> str | None:
    lo, hi = row.get("ref_low"), row.get("ref_high")
    if is_missing(lo) and is_missing(hi):
        return None
    unit = f" {row['unit']}" if not is_missing(row.get("unit")) else ""
    if not is_missing(lo) and not is_missing(hi):
        return f"{fmt_num(lo)}–{fmt_num(hi)}{unit}"
    return (f">= {fmt_num(lo)}{unit}" if not is_missing(lo) else f"<= {fmt_num(hi)}{unit}")


def source_label(row) -> str:
    sysname, doc = row.get("source_system"), row.get("source_doc_id")
    if is_missing(sysname) and is_missing(doc):
        return "Source not recorded"
    base = sysname if not is_missing(sysname) else "Source system not recorded"
    return f"{base} · {doc}" if not is_missing(doc) else f"{base} (no linked document)"


def missing_fields(table: str, row) -> list[str]:
    out = []
    for f in EXPECTED_FIELDS.get(table, []):
        v = row.get(f)
        if f == "value_num" and is_missing(v) and not is_missing(row.get("value_text")):
            continue
        if f == "unit" and is_missing(row.get("value_num")):
            continue
        if is_missing(v):
            out.append(f)
    return out


# ---- unified record view --------------------------------------------------------------------------
RECORD_COLUMNS = ["key", "table", "category", "date", "title", "details", "status", "source", "source_system",
                  "source_doc_id", "encounter_id", "obs_name", "missing"]


def build_records(bundle: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per clinical record from every table, in a common shape. SOURCE data; nothing is altered."""
    rows: list[dict] = []

    def add(table, row, category, date_value, title, details, status):
        rows.append(dict(key=row[ID_COLUMN[table]], table=table, category=category,
                         date=pd.to_datetime(date_value, errors="coerce") if not is_missing(date_value) else pd.NaT,
                         title=title, details=details, status=status if not is_missing(status) else None,
                         source=source_label(row), source_system=row.get("source_system"),
                         source_doc_id=row.get("source_doc_id"), encounter_id=row.get("encounter_id"),
                         obs_name=row.get("display") if table == "observations" else None,
                         missing=missing_fields(table, row)))

    for _, r in bundle["encounters"].iterrows():
        end = f" to {fmt_date(r['end_date'])}" if not is_missing(r["end_date"]) and r["end_date"] != r["start_date"] else ""
        det = f"{str(r['enc_class']).capitalize()} · {r['department'] or 'department not recorded'}{end}"
        if not is_missing(r["disposition"]):
            det += f" · Disposition: {r['disposition']}"
        add("encounters", r, "Encounter", r["start_date"], r["reason"] if not is_missing(r["reason"]) else "Reason not recorded", det, r["status"])
    for _, r in bundle["conditions"].iterrows():
        det = f"Verification: {r['verification_status'] or 'not recorded'}"
        if not is_missing(r["note"]):
            det += f" · {r['note']}"
        add("conditions", r, "Condition", r["onset_date"], r["display"], det, r["clinical_status"])
    for _, r in bundle["observations"].iterrows():
        cat = "Laboratory" if r["category"] == "laboratory" else "Vital sign"
        det = []
        rr = ref_range_str(r)
        det.append(f"Source reference range: {rr}" if rr else "No reference range in source")
        if not is_missing(r["flag"]):
            det.append(f"Source flag: {r['flag']}")
        add("observations", r, cat, r["effective_date"], f"{r['display']}: {value_str(r)}", " · ".join(det), r["status"])
    for _, r in bundle["medications"].iterrows():
        dose = " ".join(str(x) for x in (r["dose"], r["route"], r["frequency"]) if not is_missing(x)) or "dose details not recorded"
        det = dose
        if not is_missing(r["indication"]):
            det += f" · Indication: {r['indication']}"
        if not is_missing(r["end_date"]):
            det += f" · Ended: {fmt_date(r['end_date'])}"
        add("medications", r, "Medication", r["start_date"], f"{r['name']}", det, r["status"])
    for _, r in bundle["procedures"].iterrows():
        add("procedures", r, "Procedure", r["performed_date"], r["display"], r["note"] if not is_missing(r["note"]) else "No further detail recorded", r["status"])
    for _, r in bundle["documents"].iterrows():
        add("documents", r, r["doc_type"], r["doc_date"], r["title"], f"Author: {r['author_role'] if not is_missing(r['author_role']) else 'not recorded'}", None)
    for _, r in bundle["tasks"].iterrows():
        det = f"{r['task_type']} · Due: {fmt_date(r['due_date']) if not is_missing(r['due_date']) else 'not recorded'}"
        add("tasks", r, "Follow-up task", r["documented_date"], r["description"], det, r["status"] if not is_missing(r["status"]) else "status not recorded")

    df = pd.DataFrame(rows, columns=RECORD_COLUMNS)
    return df.sort_values("date", na_position="last", kind="stable").reset_index(drop=True)


def raw_record(bundle: dict[str, pd.DataFrame], key: str) -> tuple[str, dict] | None:
    """Look up a source row by its identifier prefix (e.g. 'OBS-0012')."""
    table = PREFIX_TABLE.get(key.split("-")[0])
    if not table:
        return None
    df = bundle[table]
    hit = df[df[ID_COLUMN[table]] == key]
    if hit.empty:
        return None
    return table, {k: (None if is_missing(v) else v) for k, v in hit.iloc[0].to_dict().items()}


# ---- normalisation --------------------------------------------------------------------------------
def normalise_term(text) -> tuple[str, bool]:
    if is_missing(text):
        return text, False
    key = str(text).strip().lower()
    if key in TERM_RULES:
        return TERM_RULES[key], True
    return str(text), False


def normalisation_log(bundle: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Documented transformations: original (SOURCE) text next to the NORMALISED term."""
    rows = []
    for table, col, idcol in (("conditions", "display", "condition_id"), ("medications", "name", "medication_id")):
        for _, r in bundle[table].iterrows():
            norm, changed = normalise_term(r[col])
            if changed:
                rows.append(dict(table=table, record_id=r[idcol], field=col, original_source_text=r[col],
                                 normalised_text=norm, rule="Synonym / brand-name mapping (illustrative list)"))
    return pd.DataFrame(rows, columns=["table", "record_id", "field", "original_source_text", "normalised_text", "rule"])


def norm_key(text) -> str:
    return normalise_term(text)[0].strip().lower() if not is_missing(text) else ""
