"""Synthetic patient generator for CareFlow.

Everything here is FICTIONAL. The records are hand-authored (not random) so that each patient
tells a consistent story and each demonstrates a particular feature of the app:

  SYN-0001  Eleanor Whitcombe   rich longitudinal history, many trends, clean metadata
  SYN-0002  Rahul Deshmukh      recent admission, outstanding follow-up imaging, medication with a passed end date
  SYN-0003  Chloe Nakamura      INCOMPLETE record: missing dates, units, values, duplicates, terminology differences
  SYN-0004  Tobias Lindqvist    orthopaedic admission, conflicting medication doses, medication not reviewed for a long time
  SYN-0005  Amara Okafor        short history with two related trends (haemoglobin and ferritin)
  SYN-0006  Samuel Brooks       MISSING SOURCE metadata, conflicting entries, mixed units, inconsistent terms

Flags and reference ranges are stored as if they were supplied by the source laboratory. CareFlow
never computes its own "normal / abnormal" judgement.
"""
from __future__ import annotations

import json
from pathlib import Path

SRC_EHR = "Synthetic Hospital EHR"
SRC_LAB = "Synthetic Laboratory System"
SRC_RIS = "Synthetic Radiology System"
SRC_VIT = "Synthetic EHR (vital signs)"
SRC_RX = "Synthetic Prescribing System"
SRC_GP = "Synthetic GP System"

TABLES = ["patients", "encounters", "conditions", "observations",
          "medications", "procedures", "documents", "tasks"]

# key: (display, LOINC code, unit, category, (female_low, female_high), (male_low, male_high))
# LOINC / SNOMED codes are used for illustration; they are not validated against a terminology server.
CATALOG = {
    "creat":   ("Creatinine", "2160-0", "mg/dL", "laboratory", (0.6, 1.1), (0.7, 1.3)),
    "egfr":    ("eGFR", "62238-1", "mL/min/1.73m2", "laboratory", (60, None), (60, None)),
    "hba1c":   ("HbA1c", "4548-4", "%", "laboratory", (None, None), (None, None)),
    "hb":      ("Haemoglobin", "718-7", "g/dL", "laboratory", (11.5, 15.5), (13.0, 17.0)),
    "glucose": ("Glucose (plasma)", "2345-7", "mmol/L", "laboratory", (None, None), (None, None)),
    "k":       ("Potassium", "2823-3", "mmol/L", "laboratory", (3.5, 5.3), (3.5, 5.3)),
    "crp":     ("C-reactive protein", "1988-5", "mg/L", "laboratory", (None, 5), (None, 5)),
    "wbc":     ("White cell count", "6690-2", "x10^9/L", "laboratory", (4.0, 11.0), (4.0, 11.0)),
    "ferritin": ("Ferritin", "2276-4", "ng/mL", "laboratory", (15, 150), (30, 400)),
    "sbp":     ("Systolic blood pressure", "8480-6", "mmHg", "vital-signs", (None, None), (None, None)),
    "dbp":     ("Diastolic blood pressure", "8462-4", "mmHg", "vital-signs", (None, None), (None, None)),
    "hr":      ("Heart rate", "8867-4", "bpm", "vital-signs", (None, None), (None, None)),
    "spo2":    ("Oxygen saturation", "59408-5", "%", "vital-signs", (None, None), (None, None)),
    "temp":    ("Body temperature", "8310-5", "°C", "vital-signs", (None, None), (None, None)),
    "weight":  ("Body weight", "29463-7", "kg", "vital-signs", (None, None), (None, None)),
}

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"


class Builder:
    def __init__(self) -> None:
        self.t: dict[str, list[dict]] = {k: [] for k in TABLES}
        self._n: dict[str, int] = {}
        self.sex: dict[str, str] = {}

    def _id(self, prefix: str) -> str:
        self._n[prefix] = self._n.get(prefix, 0) + 1
        return f"{prefix}-{self._n[prefix]:04d}"

    # ---- record creators -------------------------------------------------------------------
    def patient(self, pid, given, family, dob, sex, city, language="English", source=SRC_EHR):
        self.sex[pid] = sex
        self.t["patients"].append(dict(patient_id=pid, given_name=given, family_name=family,
                                       birth_date=dob, sex=sex, city=city, language=language,
                                       source_system=source, synthetic=1))
        return pid

    def encounter(self, pid, start, end, cls, etype, reason, dept, status="finished",
                  disposition=None, source=SRC_EHR):
        eid = self._id("ENC")
        self.t["encounters"].append(dict(encounter_id=eid, patient_id=pid, start_date=start, end_date=end,
                                         enc_class=cls, enc_type=etype, reason=reason, department=dept,
                                         status=status, disposition=disposition, source_system=source,
                                         source_doc_id=None))
        return eid

    def doc(self, pid, enc, dtype, title, date, author, body, source=SRC_EHR):
        did = self._id("DOC")
        self.t["documents"].append(dict(document_id=did, patient_id=pid, encounter_id=enc, doc_type=dtype,
                                        title=title, doc_date=date, author_role=author, body=body,
                                        source_system=source))
        if enc and dtype in ("Clinical note", "Discharge summary"):
            for e in self.t["encounters"]:
                if e["encounter_id"] == enc and not e["source_doc_id"]:
                    e["source_doc_id"] = did
        return did

    def condition(self, pid, enc, display, code, onset, status="active", verification="confirmed",
                  note=None, source=SRC_EHR, doc=None):
        cid = self._id("CON")
        self.t["conditions"].append(dict(condition_id=cid, patient_id=pid, encounter_id=enc, display=display,
                                         code=code, code_system=SNOMED if code else None, onset_date=onset,
                                         clinical_status=status, verification_status=verification, note=note,
                                         source_system=source, source_doc_id=doc))
        return cid

    def obs(self, pid, enc, date, key, value, source=SRC_LAB, unit="default", status="final",
            value_text=None, doc=None):
        display, code, cat_unit, cat, fr, mr = CATALOG[key]
        low, high = fr if self.sex[pid] == "female" else mr
        flag = None
        if source and value is not None:
            if low is not None and value < low:
                flag = "L"
            elif high is not None and value > high:
                flag = "H"
        if source is None:      # source gave no reference information in this scenario
            flag = None
        if cat == "vital-signs" and source == SRC_LAB:
            source = SRC_VIT
        oid = self._id("OBS")
        self.t["observations"].append(dict(
            observation_id=oid, patient_id=pid, encounter_id=enc, category=cat, display=display, code=code,
            code_system=LOINC, value_num=value, value_text=value_text,
            unit=cat_unit if unit == "default" else unit, ref_low=low if source else None,
            ref_high=high if source else None, flag=flag, status=status, effective_date=date,
            source_system=source, source_doc_id=doc))
        return oid

    def med(self, pid, enc, name, dose, route, freq, status, start, end=None, indication=None,
            reviewed=None, note=None, source=SRC_RX, doc=None):
        mid = self._id("MED")
        self.t["medications"].append(dict(medication_id=mid, patient_id=pid, encounter_id=enc, name=name,
                                          dose=dose, route=route, frequency=freq, status=status,
                                          start_date=start, end_date=end, indication=indication,
                                          last_reviewed=reviewed, note=note, source_system=source,
                                          source_doc_id=doc))
        return mid

    def proc(self, pid, enc, display, code, date, status="completed", note=None, source=SRC_EHR, doc=None):
        prid = self._id("PRO")
        self.t["procedures"].append(dict(procedure_id=prid, patient_id=pid, encounter_id=enc, display=display,
                                         code=code, code_system=SNOMED if code else None, performed_date=date,
                                         status=status, note=note, source_system=source, source_doc_id=doc))
        return prid

    def task(self, pid, enc, desc, ttype, status, due, documented, doc=None, source=SRC_EHR):
        tid = self._id("TSK")
        self.t["tasks"].append(dict(task_id=tid, patient_id=pid, encounter_id=enc, description=desc,
                                    task_type=ttype, status=status, due_date=due, documented_date=documented,
                                    source_system=source if (doc or source) else None, source_doc_id=doc))
        return tid

    # ---- derived laboratory report documents ----------------------------------------------------
    def finalize(self) -> dict:
        """Create one 'Laboratory report' document per patient/date for laboratory observations that
        have a source system, and link the observations to it. The report text is built from the
        observation rows, so the report and the observations can never disagree."""
        groups: dict[tuple, list[dict]] = {}
        for o in self.t["observations"]:
            if o["category"] == "laboratory" and o["source_system"] == SRC_LAB and o["effective_date"]:
                groups.setdefault((o["patient_id"], o["effective_date"]), []).append(o)
        for (pid, date), rows in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            lines = [f"LABORATORY REPORT (synthetic) - collected {date}", "Results as reported by the source system:"]
            for o in rows:
                val = "value not recorded" if o["value_num"] is None else f"{o['value_num']:g}"
                unit = f" {o['unit']}" if o["unit"] else " (unit not recorded)"
                ref = ""
                if o["ref_low"] is not None or o["ref_high"] is not None:
                    lo = "" if o["ref_low"] is None else f"{o['ref_low']:g}"
                    hi = "" if o["ref_high"] is None else f"{o['ref_high']:g}"
                    ref = f"  [source reference range: {lo}-{hi}]"
                flag = f"  [source flag: {o['flag']}]" if o["flag"] else ""
                lines.append(f"- {o['display']}: {val}{unit}{ref}{flag}")
            enc = rows[0]["encounter_id"]
            did = self.doc(pid, enc, "Laboratory report", f"Laboratory report {date}", date,
                           "Laboratory", "\n".join(lines), source=SRC_LAB)
            for o in rows:
                o["source_doc_id"] = did
        return self.t


def build_dataset() -> dict:
    b = Builder()
    _p1(b); _p2(b); _p3(b); _p4(b); _p5(b); _p6(b)
    return b.finalize()


# --------------------------------------------------------------------------------------------------
def _p1(b: Builder) -> None:
    p = b.patient("SYN-0001", "Eleanor", "Whitcombe", "1957-03-14", "female", "Northbridge")
    e1 = b.encounter(p, "2023-02-06", "2023-02-06", "outpatient", "Clinic visit", "Annual diabetes review", "Diabetes clinic")
    e2 = b.encounter(p, "2023-08-21", "2023-08-21", "outpatient", "Clinic visit", "Diabetes and kidney function review", "Diabetes clinic")
    e3 = b.encounter(p, "2024-03-11", "2024-03-11", "outpatient", "Clinic visit", "Blood pressure review", "General medicine clinic")
    e4 = b.encounter(p, "2024-11-04", "2024-11-09", "inpatient", "Hospital admission", "Lower respiratory tract infection", "Acute medicine", disposition="Discharged home")
    e5 = b.encounter(p, "2025-06-16", "2025-06-16", "outpatient", "Clinic visit", "Diabetes review", "Diabetes clinic")
    e6 = b.encounter(p, "2026-02-23", "2026-02-23", "outpatient", "Clinic visit", "Kidney clinic review", "Renal clinic")
    e7 = b.encounter(p, "2026-10-19", "2026-10-19", "outpatient", "Clinic visit", "Routine diabetes and kidney review", "Diabetes clinic")

    b.doc(p, e1, "Clinical note", "Diabetes clinic note", "2023-02-06", "Diabetes nurse specialist",
          "Clinic note (synthetic). Annual diabetes review. Observations and laboratory results from this visit are recorded separately.")
    b.doc(p, e2, "Clinical note", "Diabetes clinic note", "2023-08-21", "Consultant physician",
          "Clinic note (synthetic). Creatinine and eGFR recorded below the laboratory's reference limits. Condition recorded: chronic kidney disease stage 3.")
    b.doc(p, e3, "Clinical note", "General medicine clinic note", "2024-03-11", "Consultant physician",
          "Clinic note (synthetic). Blood pressure reviewed. Amlodipine 5 mg once daily started at this visit.")
    b.doc(p, e4, "Imaging report", "Chest X-ray report", "2024-11-04", "Radiologist",
          "Chest X-ray (synthetic report). Right lower zone consolidation described. No pleural effusion described.", source=SRC_RIS)
    b.doc(p, e4, "Discharge summary", "Discharge summary - admission 4 to 9 Nov 2024", "2024-11-09", "Ward physician",
          "Discharge summary (synthetic). Admitted with a lower respiratory tract infection. Amoxicillin course completed in hospital. "
          "Creatinine was higher than the previous clinic value on admission and lower at discharge (values in laboratory reports). "
          "Metformin dose reduced to 500 mg once daily at discharge. Repeat kidney function blood test requested after discharge.")
    b.doc(p, e5, "Clinical note", "Diabetes clinic note", "2025-06-16", "Consultant physician",
          "Clinic note (synthetic). Empagliflozin 10 mg once daily started at this visit.")
    b.doc(p, e6, "Clinical note", "Renal clinic note", "2026-02-23", "Renal physician",
          "Clinic note (synthetic). Kidney function reviewed. No medication changes documented at this visit.")
    n7 = b.doc(p, e7, "Clinical note", "Diabetes clinic note", "2026-10-19", "Consultant physician",
               "Clinic note (synthetic). Routine review. Plan as documented: repeat creatinine and eGFR in 3 months; "
               "kidney clinic review in 6 months; retinal screening to be arranged.")
    us = b.doc(p, None, "Imaging report", "Renal tract ultrasound report", "2023-09-12", "Radiologist",
               "Ultrasound of the kidneys (synthetic report). Report text not itemised in this synthetic dataset.", source=SRC_RIS)

    b.condition(p, None, "Hypertension", "38341003", "2012-09-01", doc=None)
    b.condition(p, None, "Type 2 diabetes mellitus", "44054006", "2016-05-10")
    b.condition(p, e2, "Chronic kidney disease stage 3", "433144002", "2023-08-21", note="Recorded at clinic review.")
    b.condition(p, e4, "Lower respiratory tract infection", None, "2024-11-04", status="resolved",
                note="Recorded as resolved in the discharge summary.")

    rows = {
        "2023-02-06": (e1, dict(creat=1.1, egfr=56, hba1c=7.8, hb=12.4, glucose=8.9, sbp=148, dbp=86, hr=78, weight=82.5)),
        "2023-08-21": (e2, dict(creat=1.3, egfr=46, hba1c=7.4, hb=12.1, glucose=8.1, k=4.6, sbp=144, dbp=84, hr=76)),
        "2024-03-11": (e3, dict(creat=1.3, egfr=45, hba1c=7.1, hb=11.8, glucose=7.6, sbp=152, dbp=90, hr=80, weight=81.0)),
        "2024-11-04": (e4, dict(creat=1.9, egfr=29, hb=10.9, k=5.4, crp=86, wbc=14.8, sbp=118, dbp=70, hr=96, spo2=93, temp=38.2)),
        "2024-11-08": (e4, dict(creat=1.5, egfr=38, hb=10.6, k=4.9, crp=22, wbc=9.6, spo2=96, temp=36.9)),
        "2025-01-06": (None, dict(creat=1.5, egfr=38, k=4.7)),
        "2025-06-16": (e5, dict(creat=1.4, egfr=41, hba1c=7.6, hb=11.2, glucose=9.2, sbp=138, dbp=82, hr=74, weight=79.2)),
        "2026-02-23": (e6, dict(creat=1.5, egfr=38, hba1c=7.2, hb=11.0, glucose=8.0, k=4.8, sbp=136, dbp=80, hr=72)),
        "2026-10-19": (e7, dict(creat=1.5, egfr=37, hba1c=6.9, hb=11.3, glucose=7.4, sbp=132, dbp=78, hr=70, weight=78.4)),
    }
    for date, (enc, vals) in rows.items():
        for key, v in vals.items():
            b.obs(p, enc, date, key, v)

    b.proc(p, e1, "Diabetic retinal screening", None, "2023-03-02", source=SRC_EHR)
    b.proc(p, e4, "Chest X-ray", "399208008", "2024-11-04", note="See linked imaging report.", source=SRC_RIS)
    b.proc(p, None, "Renal tract ultrasound", None, "2023-09-12", note="See linked imaging report.", source=SRC_RIS, doc=us)

    rv = "2026-10-19"
    b.med(p, None, "Ramipril", "5 mg", "oral", "once daily", "active", "2013-01-10", indication="Hypertension", reviewed=rv)
    b.med(p, None, "Atorvastatin", "20 mg", "oral", "at night", "active", "2016-06-01", reviewed=rv)
    b.med(p, None, "Metformin", "500 mg", "oral", "twice daily", "stopped", "2016-06-01", end="2024-11-09",
          indication="Type 2 diabetes mellitus", note="Dose reduced at discharge 9 Nov 2024; see next record.", reviewed="2024-11-09")
    b.med(p, e4, "Metformin", "500 mg", "oral", "once daily", "active", "2024-11-09", indication="Type 2 diabetes mellitus", reviewed=rv)
    b.med(p, e3, "Amlodipine", "5 mg", "oral", "once daily", "active", "2024-03-11", indication="Hypertension", reviewed=rv)
    b.med(p, e4, "Amoxicillin", "500 mg", "oral", "three times daily", "completed", "2024-11-04", end="2024-11-09",
          indication="Lower respiratory tract infection", reviewed="2024-11-09")
    b.med(p, e5, "Empagliflozin", "10 mg", "oral", "once daily", "active", "2025-06-16", indication="Type 2 diabetes mellitus", reviewed=rv)

    b.task(p, e4, "Repeat kidney function blood test after discharge", "investigation", "completed", "2025-01-06", "2024-11-09", doc=None)
    b.task(p, e7, "Repeat creatinine and eGFR in 3 months", "investigation", "open", "2027-01-19", "2026-10-19", doc=n7)
    b.task(p, e7, "Kidney clinic review in 6 months", "follow-up", "open", "2027-04-19", "2026-10-19", doc=n7)
    b.task(p, e7, "Arrange retinal screening", "follow-up", "open", None, "2026-10-19", doc=n7)


def _p2(b: Builder) -> None:
    p = b.patient("SYN-0002", "Rahul", "Deshmukh", "1972-09-02", "male", "Eastvale")
    e1 = b.encounter(p, "2025-04-10", "2025-04-10", "outpatient", "Clinic visit", "Blood pressure review", "General practice", source=SRC_GP)
    e2 = b.encounter(p, "2026-09-14", "2026-09-19", "inpatient", "Hospital admission", "Community-acquired pneumonia", "Acute medicine", disposition="Discharged home")
    b.doc(p, e1, "Clinical note", "GP consultation note", "2025-04-10", "General practitioner",
          "Consultation note (synthetic). Blood pressure reviewed. Amlodipine continued.", source=SRC_GP)
    b.doc(p, e2, "Imaging report", "Chest X-ray report", "2026-09-14", "Radiologist",
          "Chest X-ray (synthetic report). Left lower zone airspace opacification described.", source=SRC_RIS)
    d = b.doc(p, e2, "Discharge summary", "Discharge summary - admission 14 to 19 Sep 2026", "2026-09-19", "Ward physician",
              "Discharge summary (synthetic). Admitted with community-acquired pneumonia. Oral antibiotics prescribed to continue after "
              "discharge until 21 Sep 2026. Follow-up chest X-ray in 6 weeks advised. GP review in 2 weeks advised.")
    b.condition(p, None, "Hypertension", "38341003", "2019-03-01", source=SRC_GP)
    b.condition(p, e2, "Community-acquired pneumonia", "233604007", "2026-09-14", status="active",
                note="Treatment course documented in discharge summary; follow-up imaging requested.", doc=d)
    for date, enc, vals in [
        ("2025-04-10", e1, dict(sbp=142, dbp=88, hr=72, weight=91.0)),
        ("2026-09-14", e2, dict(crp=182, wbc=16.2, creat=0.9, sbp=124, dbp=76, hr=104, spo2=91, temp=38.9)),
        ("2026-09-16", e2, dict(crp=96, wbc=12.1, spo2=94, temp=37.8, hr=90)),
        ("2026-09-19", e2, dict(crp=28, wbc=8.9, spo2=96, temp=36.8, hr=76)),
    ]:
        for k, v in vals.items():
            b.obs(p, enc, date, k, v, source=SRC_GP if enc == e1 else SRC_LAB)
    b.proc(p, e2, "Chest X-ray", "399208008", "2026-09-14", note="See linked imaging report.", source=SRC_RIS)
    b.med(p, None, "Amlodipine", "5 mg", "oral", "once daily", "active", "2019-03-01", indication="Hypertension",
          reviewed="2025-04-10", source=SRC_GP)
    b.med(p, e2, "Co-amoxiclav", "625 mg", "oral", "three times daily", "active", "2026-09-14", end="2026-09-21",
          indication="Community-acquired pneumonia", reviewed="2026-09-19", note="Course end date recorded as 21 Sep 2026.", doc=d)
    b.task(p, e2, "Follow-up chest X-ray in 6 weeks", "investigation", "open", "2026-10-31", "2026-09-19", doc=d)
    b.task(p, e2, "GP review in 2 weeks", "follow-up", None, "2026-10-03", "2026-09-19", doc=d)


def _p3(b: Builder) -> None:
    p = b.patient("SYN-0003", "Chloe", "Nakamura", "1991-11-20", "female", "Lakeside", source=SRC_GP)
    e1 = b.encounter(p, "2024-06-10", "2024-06-10", "outpatient", "Clinic visit", "Asthma review", "General practice", source=SRC_GP)
    e2 = b.encounter(p, "2025-03-04", "2025-03-04", "outpatient", "Clinic visit", "Headache assessment", "General practice", source=SRC_GP)
    e3 = b.encounter(p, None, None, "outpatient", "Clinic visit", "Respiratory review (date not recorded)", "General practice", source=SRC_GP)
    b.doc(p, e1, "Clinical note", "GP consultation note", "2024-06-10", "General practitioner",
          "Consultation note (synthetic). Asthma review. Inhaler technique discussed.", source=SRC_GP)
    b.doc(p, e2, "Clinical note", "GP consultation note", "2025-03-04", None,
          "Consultation note (synthetic). Headache assessment. Author not recorded in the source.", source=SRC_GP)
    b.condition(p, None, "Asthma", "195967001", None, source=SRC_GP, note="Onset date not recorded.")
    b.condition(p, e2, "Migraine", "37796009", "2022-09-01", verification="provisional",
                note="Recorded as provisional in the source.", source=SRC_GP)
    b.obs(p, e1, "2024-06-10", "hb", 12.2, unit=None)                      # unit missing
    b.obs(p, e2, "2025-03-04", "hb", 11.9)
    b.obs(p, e2, "2025-03-04", "ferritin", 22)
    b.obs(p, e2, "2025-03-04", "ferritin", 22)                              # exact duplicate row
    b.obs(p, e2, "2025-03-04", "crp", None, status="registered")            # value not recorded
    b.obs(p, e3, None, "spo2", 97, source=None)                            # no date, no source
    b.obs(p, e2, "2025-03-04", "weight", 64.0, source=None)                 # no source
    b.med(p, None, "Salbutamol", None, "inhaled", None, "active", None, indication="Asthma", source=SRC_GP)
    b.med(p, None, "Ventolin", "100 mcg", "inhaled", "as required", "active", "2023-01-10", indication="Asthma", reviewed="2024-06-10", source=SRC_GP)
    b.med(p, e2, "Sumatriptan", "50 mg", "oral", "as required", "active", "2022-09-15", indication="Migraine", reviewed="2025-03-04", source=SRC_GP)
    b.task(p, e1, "Review asthma control in 3 months", "follow-up", None, None, "2024-06-10", source=SRC_GP)


def _p4(b: Builder) -> None:
    p = b.patient("SYN-0004", "Tobias", "Lindqvist", "1948-06-30", "male", "Hillcrest")
    e1 = b.encounter(p, "2024-05-14", "2024-05-14", "outpatient", "Clinic visit", "Respiratory and heart rhythm review", "Respiratory clinic")
    e2 = b.encounter(p, "2025-12-02", "2025-12-12", "inpatient", "Hospital admission", "Fracture of neck of femur after a fall", "Orthopaedics", disposition="Discharged to rehabilitation unit")
    e3 = b.encounter(p, "2026-03-10", "2026-03-10", "outpatient", "Clinic visit", "Post-operative follow-up", "Orthogeriatrics clinic")
    e4 = b.encounter(p, "2026-09-15", "2026-09-15", "outpatient", "Clinic visit", "Respiratory review", "Respiratory clinic")
    b.doc(p, e1, "Clinical note", "Respiratory clinic note", "2024-05-14", "Consultant physician",
          "Clinic note (synthetic). COPD and atrial fibrillation reviewed. Medication list reviewed at this visit.")
    b.doc(p, e2, "Imaging report", "Hip X-ray report", "2025-12-02", "Radiologist",
          "Pelvis and hip X-ray (synthetic report). Fracture of the left femoral neck described.", source=SRC_RIS)
    b.doc(p, e2, "Operative note", "Operation note - hip hemiarthroplasty", "2025-12-03", "Orthopaedic surgeon",
          "Operation note (synthetic). Hemiarthroplasty of the left hip performed under spinal anaesthesia. No intra-operative complications documented.")
    d = b.doc(p, e2, "Discharge summary", "Discharge summary - admission 2 to 12 Dec 2025", "2025-12-12", "Ward physician",
              "Discharge summary (synthetic). Left femoral neck fracture treated with hemiarthroplasty. Enoxaparin continued after discharge for a documented course. "
              "Bone health assessment to be arranged. Orthogeriatric follow-up arranged.")
    b.doc(p, e3, "Clinical note", "Orthogeriatrics clinic note", "2026-03-10", "Geriatrician",
          "Clinic note (synthetic). Post-operative follow-up attended.")
    b.doc(p, e4, "Clinical note", "Respiratory clinic note", "2026-09-15", "Respiratory nurse",
          "Clinic note (synthetic). COPD review. Inhaler use reviewed.")
    b.condition(p, None, "Chronic obstructive pulmonary disease", "13645005", "2015-02-01")
    b.condition(p, None, "Atrial fibrillation", "49436004", "2019-08-20")
    b.condition(p, e2, "Fracture of neck of femur", "5913000", "2025-12-02", note="Treated surgically; see procedure record.", doc=d)
    for date, enc, vals in [
        ("2024-05-14", e1, dict(hb=13.1, creat=1.2, spo2=94, hr=82, sbp=134, dbp=80)),
        ("2025-12-04", e2, dict(hb=9.8, creat=1.3, spo2=95, hr=88)),
        ("2025-12-06", e2, dict(hb=9.2, spo2=95)),
        ("2025-12-10", e2, dict(hb=10.1, creat=1.2, spo2=94)),
        ("2026-03-10", e3, dict(hb=11.4, creat=1.2, spo2=94, hr=78, sbp=130, dbp=78)),
        ("2026-09-15", e4, dict(hb=12.0, creat=1.2, spo2=93, hr=80, sbp=128, dbp=76)),
    ]:
        for k, v in vals.items():
            b.obs(p, enc, date, k, v)
    b.proc(p, None, "Echocardiogram", "40701008", "2024-06-12", source=SRC_RIS)
    b.proc(p, e2, "Hip hemiarthroplasty (left)", None, "2025-12-03", note="Code not assigned in the source record.", doc=None)
    b.med(p, None, "Tiotropium", "18 mcg", "inhaled", "once daily", "active", "2015-03-01", indication="COPD", reviewed="2026-09-15")
    b.med(p, None, "Apixaban", "5 mg", "oral", "twice daily", "active", "2019-09-01", indication="Atrial fibrillation", reviewed="2024-05-14")
    b.med(p, None, "Bisoprolol", "2.5 mg", "oral", "once daily", "active", "2019-09-01", indication="Atrial fibrillation", reviewed="2024-05-14")
    b.med(p, e2, "Bisoprolol", "5 mg", "oral", "once daily", "active", "2025-12-04", indication="Atrial fibrillation", reviewed="2025-12-12", note="Listed on the inpatient medication chart.")
    b.med(p, e2, "Enoxaparin", "40 mg", "subcutaneous", "once daily", "completed", "2025-12-03", end="2026-01-02", reviewed="2025-12-12", doc=d)
    b.med(p, e2, "Paracetamol", "1 g", "oral", "four times daily", "completed", "2025-12-02", end="2025-12-12", reviewed="2025-12-12")
    b.task(p, e2, "Orthogeriatric outpatient follow-up", "follow-up", "completed", "2026-03-10", "2025-12-12", doc=d)
    b.task(p, e2, "Bone health assessment", "investigation", "open", "2026-06-01", "2025-12-12", doc=d)


def _p5(b: Builder) -> None:
    p = b.patient("SYN-0005", "Amara", "Okafor", "1997-04-08", "female", "Riverton")
    e1 = b.encounter(p, "2025-02-12", "2025-02-12", "outpatient", "Clinic visit", "Tiredness and low haemoglobin on routine bloods", "General practice", source=SRC_GP)
    e2 = b.encounter(p, "2025-05-14", "2025-05-14", "outpatient", "Clinic visit", "Iron deficiency anaemia review", "General practice", source=SRC_GP)
    e3 = b.encounter(p, "2025-09-10", "2025-09-10", "outpatient", "Clinic visit", "Iron deficiency anaemia review", "General practice", source=SRC_GP)
    e4 = b.encounter(p, "2026-03-04", "2026-03-04", "outpatient", "Clinic visit", "Review", "General practice", source=SRC_GP)
    for e, d, txt in [(e1, "2025-02-12", "Iron deficiency anaemia recorded. Oral iron prescribed."),
                      (e2, "2025-05-14", "Review of blood results."),
                      (e3, "2025-09-10", "Review of blood results. Oral iron course recorded as completed."),
                      (e4, "2026-03-04", "Review of blood results.")]:
        b.doc(p, e, "Clinical note", "GP consultation note", d, "General practitioner", "Consultation note (synthetic). " + txt, source=SRC_GP)
    b.condition(p, None, "Asthma", "195967001", "2008-01-01", source=SRC_GP)
    b.condition(p, e1, "Iron deficiency anaemia", "87522002", "2025-02-12", source=SRC_GP)
    for date, enc, hb, fe in [("2025-02-12", e1, 9.8, 6), ("2025-05-14", e2, 10.9, 18),
                              ("2025-09-10", e3, 11.8, 34), ("2026-03-04", e4, 12.6, 41)]:
        b.obs(p, enc, date, "hb", hb)
        b.obs(p, enc, date, "ferritin", fe)
    b.med(p, None, "Beclometasone inhaler", "100 mcg", "inhaled", "twice daily", "active", "2015-01-01", indication="Asthma", reviewed="2026-03-04", source=SRC_GP)
    b.med(p, e1, "Ferrous fumarate", "210 mg", "oral", "once daily", "completed", "2025-02-12", end="2025-09-10", indication="Iron deficiency anaemia", reviewed="2025-09-10", source=SRC_GP)
    b.task(p, e3, "Repeat haemoglobin and ferritin in 6 months", "investigation", "completed", "2026-03-10", "2025-09-10", source=SRC_GP)


def _p6(b: Builder) -> None:
    p = b.patient("SYN-0006", "Samuel", "Brooks", "1965-01-25", "male", "Westfield", source=None)
    e1 = b.encounter(p, "2023-05-09", "2023-05-09", "outpatient", "Clinic visit", "Diabetes and blood pressure review", "General practice", source=SRC_GP)
    e2 = b.encounter(p, "2024-05-14", "2024-05-14", "outpatient", "Clinic visit", "Diabetes review", "General practice", source=SRC_GP)
    e3 = b.encounter(p, "2025-11-18", "2025-11-18", "outpatient", "Clinic visit", "Annual review", "General practice", source=SRC_GP)
    b.doc(p, e1, "Clinical note", "GP consultation note", "2023-05-09", "General practitioner", "Consultation note (synthetic). Diabetes and blood pressure review.", source=SRC_GP)
    b.doc(p, e2, "Clinical note", "GP consultation note", "2024-05-14", None, "Consultation note (synthetic). Diabetes review. Author and source system not recorded.", source=None)
    n3 = b.doc(p, e3, "Clinical note", "GP consultation note", "2025-11-18", "General practitioner", "Consultation note (synthetic). Annual review. Review planned in 3 months; no date recorded.", source=SRC_GP)
    b.condition(p, None, "Hypertension", "38341003", "2018-06-01", source=SRC_GP)
    b.condition(p, None, "HTN", None, "2018-06-01", source=None)
    b.condition(p, None, "High blood pressure", None, None, source=None)
    b.condition(p, None, "Type 2 DM", "44054006", "2020-02-11", source=SRC_GP)
    b.condition(p, None, "Hyperlipidaemia", "55822004", None, source=None)
    b.obs(p, e1, "2023-05-09", "glucose", 8.4)
    b.obs(p, e1, "2023-05-09", "hba1c", 8.1)
    b.obs(p, e1, "2023-05-09", "creat", 0.9)
    b.obs(p, e1, "2023-05-09", "sbp", 150, source=None)
    b.obs(p, e1, "2023-05-09", "dbp", 92, source=None)
    b.obs(p, e2, "2024-05-14", "glucose", 152, unit="mg/dL")                 # different unit for the same test
    b.obs(p, e2, "2024-05-14", "sbp", 136, source=SRC_GP)
    b.obs(p, e2, "2024-05-14", "sbp", 156, source=SRC_VIT)                   # same test/date, different value
    b.obs(p, e3, "2025-11-18", "glucose", 9.1)
    b.obs(p, e3, "2025-11-18", "hba1c", 7.6)
    b.obs(p, e3, "2025-11-18", "creat", 1.0)
    b.obs(p, e3, "2025-11-18", "weight", 96.2, source=None)
    b.med(p, None, "Metformin", "500 mg", "oral", "twice daily", "active", "2020-02-11", indication="Type 2 diabetes mellitus", source=SRC_GP)
    b.med(p, e2, "Metformin", "500 mg", "oral", "twice daily", "stopped", "2020-02-11", end="2024-05-14", source=None)
    b.med(p, None, "Ramipril", "2.5 mg", "oral", "once daily", "active", "2018-06-01", indication="Hypertension", source=SRC_GP)
    b.med(p, None, "Atorvastatin", "20 mg", None, None, "active", "2021-01-01", source=None)
    b.task(p, e3, "Review in 3 months", "follow-up", "open", None, "2025-11-18", doc=n3, source=SRC_GP)


# --------------------------------------------------------------------------------------------------
def generate_dataset() -> dict:
    return build_dataset()


def write_json(path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"_label": "SYNTHETIC DATA - fictional patients created for the CareFlow prototype. Not real patient data.",
               **generate_dataset()}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    data = generate_dataset()
    for k, v in data.items():
        print(k, len(v))
