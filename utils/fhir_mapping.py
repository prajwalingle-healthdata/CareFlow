"""Illustrative mapping of CareFlow records to HL7 FHIR R4 (4.0.1) resources.

IMPORTANT: this is a *FHIR-inspired* mapping. It has NOT been validated with the official HL7 validator
and CareFlow makes no claim of FHIR conformance. `validate_resource` is a deliberately simplified
structural check (required elements, status codes, date formats) for teaching purposes only.

Every mapper returns (resource, issues). `issues` lists anything that could not be represented
faithfully (for example a missing code, or a free-text dose) so that limitations are visible instead
of hidden.
"""
from __future__ import annotations

import base64
import re
from typing import Any

import pandas as pd

BASE = "http://example.org/fhir"  # placeholder base URL for fullUrl values
ID_SYSTEM = "http://example.org/careflow/synthetic-patient-id"
UCUM = "http://unitsofmeasure.org"
UCUM_CODES = {"mg/dL": "mg/dL", "g/dL": "g/dL", "%": "%", "mmol/L": "mmol/L", "mmHg": "mm[Hg]",
              "bpm": "/min", "ng/mL": "ng/mL", "mg/L": "mg/L", "kg": "kg", "°C": "Cel",
              "x10^9/L": "10*9/L", "mL/min/1.73m2": "mL/min/{1.73_m2}"}

ENC_CLASS = {"inpatient": ("IMP", "inpatient encounter"), "outpatient": ("AMB", "ambulatory"),
             "emergency": ("EMER", "emergency")}

VALID_STATUS = {
    "Encounter": {"planned", "arrived", "triaged", "in-progress", "onleave", "finished", "cancelled", "entered-in-error", "unknown"},
    "Observation": {"registered", "preliminary", "final", "amended", "corrected", "cancelled", "entered-in-error", "unknown"},
    "MedicationRequest": {"active", "on-hold", "cancelled", "completed", "entered-in-error", "stopped", "draft", "unknown"},
    "MedicationStatement": {"active", "completed", "entered-in-error", "intended", "stopped", "on-hold", "unknown", "not-taken"},
    "Procedure": {"preparation", "in-progress", "not-done", "on-hold", "stopped", "completed", "entered-in-error", "unknown"},
    "DiagnosticReport": {"registered", "partial", "preliminary", "final", "amended", "corrected", "appended", "cancelled", "entered-in-error", "unknown"},
    "DocumentReference": {"current", "superseded", "entered-in-error"},
}
REQUIRED = {
    "Patient": [],
    "Encounter": ["status", "class", "subject"],
    "Observation": ["status", "code", "subject"],
    "Condition": ["code", "subject"],
    "MedicationRequest": ["status", "intent", "medicationCodeableConcept", "subject"],
    "MedicationStatement": ["status", "medicationCodeableConcept", "subject"],
    "Procedure": ["status", "code", "subject"],
    "DiagnosticReport": ["status", "code", "subject"],
    "DocumentReference": ["status", "content"],
}
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

MAPPING_TABLE = [
    ("Patient profile", "patients", "Patient", "Name, gender, birthDate, identifier, address. Marked with meta.tag HTEST (test data)."),
    ("Hospital / clinic encounter", "encounters", "Encounter", "class, period, reasonCode (free text), status."),
    ("Laboratory result / vital sign", "observations", "Observation", "LOINC code, valueQuantity (UCUM units), referenceRange and interpretation copied from the source."),
    ("Recorded diagnosis", "conditions", "Condition", "SNOMED CT code where present, clinicalStatus, verificationStatus, onsetDateTime."),
    ("Prescription", "medications", "MedicationRequest", "Free-text medication and dosage (no RxNorm/dm+d coding). intent assumed 'order'."),
    ("Medication (patient statement view)", "medications", "MedicationStatement", "Alternative view of the same medication records."),
    ("Procedure record", "procedures", "Procedure", "Code where present, performedDateTime, status."),
    ("Laboratory / imaging report", "documents", "DiagnosticReport", "Lab reports reference their Observations; imaging reports carry the report text in conclusion."),
    ("Clinical document", "documents", "DocumentReference", "Notes and discharge summaries; text carried as base64 attachment."),
    ("Documented follow-up task", "tasks", "(not mapped)", "Would map to Task or ServiceRequest; not implemented in this prototype."),
]


def mapping_table() -> pd.DataFrame:
    return pd.DataFrame(MAPPING_TABLE, columns=["Application record", "Source table", "FHIR resource concept", "Notes on this prototype's mapping"])


# ---- helpers --------------------------------------------------------------------------------------
def _has(v: Any) -> bool:
    return v is not None and not (isinstance(v, float) and pd.isna(v)) and str(v).strip() != ""


def _ref(rtype: str, rid: str) -> dict:
    return {"reference": f"{rtype}/{rid}"}


def _concept(text: str, code: str | None = None, system: str | None = None) -> dict:
    cc: dict = {"text": text}
    if _has(code):
        cc["coding"] = [{"system": system, "code": str(code), "display": text}]
    return cc


def _meta(row: dict, issues: list[str]) -> dict:
    meta: dict = {}
    if _has(row.get("source_system")):
        meta["source"] = "urn:careflow:source:" + re.sub(r"[^a-z0-9]+", "-", str(row["source_system"]).lower()).strip("-")
    else:
        issues.append("No source system recorded: meta.source omitted.")
    return meta


def _quantity(value: float, unit: str | None) -> dict:
    q: dict = {"value": float(value)}
    if _has(unit):
        q["unit"] = unit
        if unit in UCUM_CODES:
            q["system"] = UCUM
            q["code"] = UCUM_CODES[unit]
    return q


# ---- resource mappers -----------------------------------------------------------------------------
def patient_resource(r: dict) -> tuple[dict, list[str]]:
    issues: list[str] = []
    res: dict = {"resourceType": "Patient", "id": r["patient_id"],
                 "identifier": [{"system": ID_SYSTEM, "value": r["patient_id"]}],
                 "name": [{"use": "official", "family": r.get("family_name"), "given": [r.get("given_name")]}]}
    res["meta"] = _meta(r, issues)
    res["meta"].setdefault("tag", [])
    res["meta"]["tag"].append({"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason", "code": "HTEST", "display": "test health data"})
    if _has(r.get("sex")) and r["sex"] in ("male", "female", "other", "unknown"):
        res["gender"] = r["sex"]
    else:
        issues.append("Sex not recorded: gender omitted.")
    if _has(r.get("birth_date")):
        res["birthDate"] = r["birth_date"]
    else:
        issues.append("Birth date not recorded: birthDate omitted.")
    if _has(r.get("city")):
        res["address"] = [{"city": r["city"]}]
    if _has(r.get("language")):
        res["communication"] = [{"language": {"text": r["language"]}}]
    return res, issues


def encounter_resource(r: dict) -> tuple[dict, list[str]]:
    issues: list[str] = []
    code, disp = ENC_CLASS.get(r.get("enc_class"), ("AMB", "ambulatory"))
    if r.get("enc_class") not in ENC_CLASS:
        issues.append("Encounter class not recognised: 'AMB' used as a placeholder.")
    res: dict = {"resourceType": "Encounter", "id": r["encounter_id"], "meta": _meta(r, issues),
                 "status": r["status"] if r.get("status") in VALID_STATUS["Encounter"] else "unknown",
                 "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": code, "display": disp},
                 "subject": _ref("Patient", r["patient_id"])}
    period = {}
    if _has(r.get("start_date")):
        period["start"] = r["start_date"]
    else:
        issues.append("Start date not recorded: Encounter.period.start omitted.")
    if _has(r.get("end_date")):
        period["end"] = r["end_date"]
    if period:
        res["period"] = period
    if _has(r.get("reason")):
        res["reasonCode"] = [{"text": r["reason"]}]
        issues.append("Reason held as free text only (no coded reason).")
    if _has(r.get("department")):
        res["type"] = [{"text": r["department"]}]
    return res, issues


def observation_resource(r: dict) -> tuple[dict, list[str]]:
    issues: list[str] = []
    cat = r.get("category") or "laboratory"
    res: dict = {"resourceType": "Observation", "id": r["observation_id"], "meta": _meta(r, issues),
                 "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": cat}]}],
                 "code": _concept(r["display"], r.get("code"), r.get("code_system")),
                 "subject": _ref("Patient", r["patient_id"])}
    if _has(r.get("status")) and r["status"] in VALID_STATUS["Observation"]:
        res["status"] = r["status"]
    else:
        res["status"] = "unknown"
        issues.append("Result status not recorded: set to 'unknown' (required element).")
    if not _has(r.get("code")):
        issues.append("No standard code: CodeableConcept.text only.")
    if _has(r.get("encounter_id")):
        res["encounter"] = _ref("Encounter", r["encounter_id"])
    if _has(r.get("effective_date")):
        res["effectiveDateTime"] = r["effective_date"]
    else:
        issues.append("No effective date: effectiveDateTime omitted.")
    if _has(r.get("value_num")):
        res["valueQuantity"] = _quantity(r["value_num"], r.get("unit"))
        if not _has(r.get("unit")):
            issues.append("Unit not recorded: valueQuantity has no unit.")
    elif _has(r.get("value_text")):
        res["valueString"] = r["value_text"]
    else:
        res["dataAbsentReason"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/data-absent-reason", "code": "unknown", "display": "Unknown"}]}
        issues.append("No value recorded: dataAbsentReason used.")
    if _has(r.get("ref_low")) or _has(r.get("ref_high")):
        rr: dict = {}
        if _has(r.get("ref_low")):
            rr["low"] = _quantity(r["ref_low"], r.get("unit"))
        if _has(r.get("ref_high")):
            rr["high"] = _quantity(r["ref_high"], r.get("unit"))
        res["referenceRange"] = [rr]
    if _has(r.get("flag")):
        res["interpretation"] = [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": r["flag"]}],
                                  "text": "Flag as supplied by the source system"}]
    return res, issues


def condition_resource(r: dict) -> tuple[dict, list[str]]:
    issues: list[str] = []
    res: dict = {"resourceType": "Condition", "id": r["condition_id"], "meta": _meta(r, issues),
                 "code": _concept(r["display"], r.get("code"), r.get("code_system")),
                 "subject": _ref("Patient", r["patient_id"])}
    if not _has(r.get("code")):
        issues.append("No standard code: CodeableConcept.text only.")
    cs = r.get("clinical_status")
    if cs in ("active", "inactive", "resolved", "remission", "recurrence", "relapse"):
        res["clinicalStatus"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": cs}]}
    else:
        issues.append("Clinical status not recorded or not recognised: omitted.")
    vs = r.get("verification_status")
    if vs in ("confirmed", "provisional", "unconfirmed", "differential", "refuted"):
        res["verificationStatus"] = {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-ver-status", "code": vs}]}
    if _has(r.get("encounter_id")):
        res["encounter"] = _ref("Encounter", r["encounter_id"])
    if _has(r.get("onset_date")):
        res["onsetDateTime"] = r["onset_date"]
    else:
        issues.append("Onset date not recorded: onsetDateTime omitted.")
    if _has(r.get("note")):
        res["note"] = [{"text": r["note"]}]
    return res, issues


def medication_request_resource(r: dict) -> tuple[dict, list[str]]:
    issues = ["Medication held as free text (no RxNorm / dm+d code).", "Intent not recorded: 'order' assumed (required element)."]
    res: dict = {"resourceType": "MedicationRequest", "id": r["medication_id"], "meta": _meta(r, issues),
                 "status": r["status"] if r.get("status") in VALID_STATUS["MedicationRequest"] else "unknown",
                 "intent": "order", "medicationCodeableConcept": {"text": r["name"]},
                 "subject": _ref("Patient", r["patient_id"])}
    if _has(r.get("encounter_id")):
        res["encounter"] = _ref("Encounter", r["encounter_id"])
    if _has(r.get("start_date")):
        res["authoredOn"] = r["start_date"]
    else:
        issues.append("Start date not recorded: authoredOn omitted.")
    parts = [str(r[k]) for k in ("dose", "route", "frequency") if _has(r.get(k))]
    if parts:
        di: dict = {"text": " ".join(parts)}
        if _has(r.get("start_date")) or _has(r.get("end_date")):
            bounds = {k: r[s] for k, s in (("start", "start_date"), ("end", "end_date")) if _has(r.get(s))}
            di["timing"] = {"repeat": {"boundsPeriod": bounds}}
        res["dosageInstruction"] = [di]
        issues.append("Dosage held as free text; not split into structured dose and timing.")
    if len(parts) < 3:
        issues.append("Incomplete dosage information (dose, route or frequency missing).")
    if _has(r.get("indication")):
        res["reasonCode"] = [{"text": r["indication"]}]
    if _has(r.get("note")):
        res["note"] = [{"text": r["note"]}]
    return res, issues


def medication_statement_resource(r: dict) -> tuple[dict, list[str]]:
    issues = ["Medication held as free text (no RxNorm / dm+d code)."]
    res: dict = {"resourceType": "MedicationStatement", "id": r["medication_id"], "meta": _meta(r, issues),
                 "status": r["status"] if r.get("status") in VALID_STATUS["MedicationStatement"] else "unknown",
                 "medicationCodeableConcept": {"text": r["name"]}, "subject": _ref("Patient", r["patient_id"])}
    period = {k: r[s] for k, s in (("start", "start_date"), ("end", "end_date")) if _has(r.get(s))}
    if period:
        res["effectivePeriod"] = period
    else:
        issues.append("No dates recorded: effectivePeriod omitted.")
    parts = [str(r[k]) for k in ("dose", "route", "frequency") if _has(r.get(k))]
    if parts:
        res["dosage"] = [{"text": " ".join(parts)}]
    if len(parts) < 3:
        issues.append("Incomplete dosage information (dose, route or frequency missing).")
    if _has(r.get("indication")):
        res["reasonCode"] = [{"text": r["indication"]}]
    return res, issues


def procedure_resource(r: dict) -> tuple[dict, list[str]]:
    issues: list[str] = []
    res: dict = {"resourceType": "Procedure", "id": r["procedure_id"], "meta": _meta(r, issues),
                 "status": r["status"] if r.get("status") in VALID_STATUS["Procedure"] else "unknown",
                 "code": _concept(r["display"], r.get("code"), r.get("code_system")),
                 "subject": _ref("Patient", r["patient_id"])}
    if not _has(r.get("code")):
        issues.append("No standard code: CodeableConcept.text only.")
    if _has(r.get("encounter_id")):
        res["encounter"] = _ref("Encounter", r["encounter_id"])
    if _has(r.get("performed_date")):
        res["performedDateTime"] = r["performed_date"]
    else:
        issues.append("No performed date: performedDateTime omitted.")
    if _has(r.get("note")):
        res["note"] = [{"text": r["note"]}]
    return res, issues


def diagnostic_report_resource(d: dict, obs_ids: list[str] | None = None) -> tuple[dict, list[str]]:
    issues = ["Report type held as text (no LOINC report code)."]
    is_lab = d["doc_type"] == "Laboratory report"
    cat = ("LAB", "Laboratory") if is_lab else ("RAD", "Radiology")
    res: dict = {"resourceType": "DiagnosticReport", "id": d["document_id"], "meta": _meta(d, issues), "status": "final",
                 "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": cat[0], "display": cat[1]}]}],
                 "code": {"text": d["title"]}, "subject": _ref("Patient", d["patient_id"])}
    issues.append("Report status not recorded: 'final' assumed (required element).")
    if _has(d.get("encounter_id")):
        res["encounter"] = _ref("Encounter", d["encounter_id"])
    if _has(d.get("doc_date")):
        res["effectiveDateTime"] = d["doc_date"]
    else:
        issues.append("No report date: effectiveDateTime omitted.")
    if is_lab and obs_ids:
        res["result"] = [_ref("Observation", o) for o in obs_ids]
    if not is_lab and _has(d.get("body")):
        res["conclusion"] = d["body"]
    return res, issues


def document_reference_resource(d: dict) -> tuple[dict, list[str]]:
    issues = ["Author held as a role text only; no Practitioner resource created."]
    res: dict = {"resourceType": "DocumentReference", "id": d["document_id"], "meta": _meta(d, issues), "status": "current",
                 "type": {"text": d["doc_type"]}, "subject": _ref("Patient", d["patient_id"]),
                 "description": d["title"]}
    issues.append("Document status not recorded: 'current' assumed (required element).")
    if _has(d.get("doc_date")):
        res["date"] = d["doc_date"]
    else:
        issues.append("No document date: date omitted.")
    if not _has(d.get("author_role")):
        issues.append("Author role not recorded.")
    body = d.get("body") or ""
    res["content"] = [{"attachment": {"contentType": "text/plain", "title": d["title"],
                                      "data": base64.b64encode(body.encode("utf-8")).decode("ascii")}}]
    if _has(d.get("encounter_id")):
        res["context"] = {"encounter": [_ref("Encounter", d["encounter_id"])]}
    return res, issues


# ---- bundle assembly ------------------------------------------------------------------------------
def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if (isinstance(v, float) and pd.isna(v)) else v) for k, v in rec.items()} for rec in df.to_dict("records")]


def build_resources(bundle: dict[str, pd.DataFrame], medication_resource: str = "MedicationRequest") -> list[dict]:
    """Return a list of {'resource', 'issues', 'table', 'record_id'} dicts for one patient bundle."""
    out: list[dict] = []

    def add(res_issues, table, rid):
        res, issues = res_issues
        out.append({"resource": res, "issues": issues, "table": table, "record_id": rid})

    for r in _records(bundle["patients"]):
        add(patient_resource(r), "patients", r["patient_id"])
    for r in _records(bundle["encounters"]):
        add(encounter_resource(r), "encounters", r["encounter_id"])
    for r in _records(bundle["conditions"]):
        add(condition_resource(r), "conditions", r["condition_id"])
    obs_by_doc: dict[str, list[str]] = {}
    for r in _records(bundle["observations"]):
        add(observation_resource(r), "observations", r["observation_id"])
        if r.get("source_doc_id"):
            obs_by_doc.setdefault(r["source_doc_id"], []).append(r["observation_id"])
    mapper = medication_statement_resource if medication_resource == "MedicationStatement" else medication_request_resource
    for r in _records(bundle["medications"]):
        add(mapper(r), "medications", r["medication_id"])
    for r in _records(bundle["procedures"]):
        add(procedure_resource(r), "procedures", r["procedure_id"])
    for d in _records(bundle["documents"]):
        if d["doc_type"] in ("Laboratory report", "Imaging report"):
            add(diagnostic_report_resource(d, obs_by_doc.get(d["document_id"])), "documents", d["document_id"])
        else:
            add(document_reference_resource(d), "documents", d["document_id"])
    for t in _records(bundle["tasks"]):
        out.append({"resource": None, "issues": ["Follow-up tasks are not mapped in this prototype (would map to Task / ServiceRequest)."],
                    "table": "tasks", "record_id": t["task_id"]})
    return out


def build_bundle(bundle: dict[str, pd.DataFrame], medication_resource: str = "MedicationRequest") -> dict:
    entries = []
    for item in build_resources(bundle, medication_resource):
        res = item["resource"]
        if res:
            entries.append({"fullUrl": f"{BASE}/{res['resourceType']}/{res['id']}", "resource": res})
    return {"resourceType": "Bundle", "type": "collection",
            "meta": {"tag": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason", "code": "HTEST", "display": "test health data"}]},
            "entry": entries}


# ---- simplified validation ------------------------------------------------------------------------
def validate_resource(res: dict) -> list[str]:
    """SIMPLIFIED structural check only. Not a replacement for the official HL7 FHIR validator."""
    problems: list[str] = []
    rtype = res.get("resourceType")
    if rtype not in REQUIRED:
        return [f"Unknown or unsupported resourceType: {rtype!r}"]
    for field in REQUIRED[rtype]:
        if field not in res:
            problems.append(f"{rtype}: required element '{field}' is missing")
    if rtype in VALID_STATUS and "status" in res and res["status"] not in VALID_STATUS[rtype]:
        problems.append(f"{rtype}.status '{res['status']}' is not in the allowed value set")
    if "id" in res and not re.fullmatch(r"[A-Za-z0-9\-\.]{1,64}", str(res["id"])):
        problems.append(f"{rtype}.id has invalid characters")
    for key in ("birthDate", "effectiveDateTime", "onsetDateTime", "performedDateTime", "authoredOn", "date"):
        if key in res and not DATE_RE.match(str(res[key])):
            problems.append(f"{rtype}.{key} '{res[key]}' is not a valid FHIR date")
    if rtype == "Observation" and not any(k in res for k in ("valueQuantity", "valueString", "dataAbsentReason", "component")):
        problems.append("Observation: no value[x] and no dataAbsentReason")
    return problems


def validate_bundle(bundle_json: dict) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    if bundle_json.get("resourceType") != "Bundle":
        return {"Bundle": ["resourceType is not 'Bundle'"]}
    for e in bundle_json.get("entry", []):
        res = e.get("resource", {})
        probs = validate_resource(res)
        if probs:
            results[f"{res.get('resourceType')}/{res.get('id')}"] = probs
    return results
