"""Basic automated checks for CareFlow. Run from the project folder with:  pytest"""
import json
import re

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from database import database as db
from modules import analytics, data_quality
from modules.handover import build_handover, candidates
from modules.search import filter_records
from modules.summarisation import RuleBasedSummaryEngine
from utils import fhir_mapping
from utils.data_processing import build_records, normalisation_log
from utils.synthetic_data import TABLES, generate_dataset

from pathlib import Path
APP = str(Path(__file__).resolve().parent.parent / "app.py")
PIDS = [f"SYN-000{i}" for i in range(1, 7)]
FORBIDDEN = ["stable", "unstable", "urgent", "deteriorat", "recommend", "should ", "severity", "critical", "improving", "worsening"]


@pytest.fixture(scope="module")
def tmp_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    db.init_db(path)
    return path


def bundle(tmp_db, pid):
    return db.load_patient_bundle(pid, tmp_db)


# ---- data ----------------------------------------------------------------------------------------
def test_dataset_size_and_unique_ids():
    d = generate_dataset()
    assert len(d["patients"]) >= 5
    for t in TABLES:
        col = {"patients": "patient_id"}.get(t, t[:-1] + "_id" if t != "procedures" else "procedure_id")
        ids = [r[col] for r in d[t]]
        assert len(ids) == len(set(ids)), t


def test_referential_integrity():
    d = generate_dataset()
    pids = {p["patient_id"] for p in d["patients"]}
    enc = {e["encounter_id"] for e in d["encounters"]}
    docs = {x["document_id"] for x in d["documents"]}
    for t in TABLES[1:]:
        for r in d[t]:
            assert r["patient_id"] in pids
            if r.get("encounter_id"):
                assert r["encounter_id"] in enc
            if r.get("source_doc_id"):
                assert r["source_doc_id"] in docs


def test_every_patient_flagged_synthetic():
    assert all(p["synthetic"] == 1 for p in generate_dataset()["patients"])


def test_reset_restores_original_data(tmp_path):
    path = tmp_path / "r.db"
    db.init_db(path)
    before = db.table_counts(path)
    with db.get_connection(path) as c:
        c.execute("DELETE FROM observations")
        c.commit()
    assert db.table_counts(path)["observations"] == 0
    assert db.reset_database(path) == before


# ---- search / timeline ---------------------------------------------------------------------------
def test_filters_and_search(tmp_db):
    b = bundle(tmp_db, "SYN-0001")
    rec = build_records(b)
    assert set(filter_records(rec, b, categories=["Medication"])["category"]) == {"Medication"}
    sub = filter_records(rec, b, start=pd.Timestamp("2024-01-01").date(), end=pd.Timestamp("2024-12-31").date(), include_undated=False)
    assert sub["date"].between("2024-01-01", "2024-12-31").all()
    assert len(filter_records(rec, b, keyword="discharge")) >= 1          # matches linked document text/title
    assert len(filter_records(rec, b, keyword="zzzz-no-match")) == 0
    assert set(filter_records(rec, b, observations=["Creatinine"])["obs_name"]) == {"Creatinine"}
    assert filter_records(rec, b, newest_first=True)["date"].dropna().is_monotonic_decreasing


def test_undated_records_are_kept_not_invented(tmp_db):
    b = bundle(tmp_db, "SYN-0003")
    rec = build_records(b)
    assert rec["date"].isna().sum() >= 2
    assert len(filter_records(rec, b, include_undated=False)) < len(rec)


# ---- trends --------------------------------------------------------------------------------------
def test_trend_statements_do_not_overreach(tmp_db):
    obs = bundle(tmp_db, "SYN-0001")["observations"]
    crp = analytics.describe(analytics.series(obs, "C-reactive protein"))
    assert any("insufficient" in l for l in crp)
    cr = analytics.describe(analytics.series(obs, "Creatinine"))
    assert any("First recorded value" in l for l in cr)
    for l in cr + crp:
        assert not any(w in l.lower() for w in FORBIDDEN)


def test_no_reference_band_when_source_has_none(tmp_db):
    obs = bundle(tmp_db, "SYN-0001")["observations"]
    _, _, note = analytics.build_figure(obs, "HbA1c")
    assert note and "No reference range" in note
    fig, _, note2 = analytics.build_figure(obs, "Creatinine")
    assert note2 is None and len(fig.layout.shapes) == 1


def test_mixed_units_not_converted(tmp_db):
    obs = bundle(tmp_db, "SYN-0006")["observations"]
    _, _, note = analytics.build_figure(obs, "Glucose (plasma)")
    assert "NOT been converted" in note


# ---- summary -------------------------------------------------------------------------------------
@pytest.mark.parametrize("pid", PIDS)
def test_summary_sections_and_sources_exist(tmp_db, pid):
    b = bundle(tmp_db, pid)
    s = RuleBasedSummaryEngine().generate(b)
    assert len(s.sections) == 10
    known = set()
    for t in TABLES:
        known |= set(b[t].iloc[:, 0])
    for sec in s.sections:
        assert sec.statements
        for i in sec.source_ids:
            assert i in known, f"{pid}: unknown source {i}"
    text = s.to_text().lower()
    assert not any(w in text for w in FORBIDDEN)


def test_summary_preserves_dates_and_units(tmp_db):
    t = RuleBasedSummaryEngine().generate(bundle(tmp_db, "SYN-0001")).to_text()
    assert "6 Feb 2023" in t and "mg/dL" in t and "Source reference range: 0.6" in t


# ---- handover ------------------------------------------------------------------------------------
@pytest.mark.parametrize("pid", PIDS)
def test_handover_safe_and_structured(tmp_db, pid):
    b = bundle(tmp_db, pid)
    c = candidates(b)
    text, used = build_handover(b, set(c[c["Include"]]["ID"]))
    assert "AI-assisted or system-generated handovers are drafts" in text
    for i in range(1, 13):
        assert re.search(rf"^{i}\. ", text, re.M)
    assert not any(w in text.lower() for w in FORBIDDEN)
    assert "ready for transfer" not in text.lower() and "clinically complete" not in text.lower()


def test_handover_respects_exclusions(tmp_db):
    b = bundle(tmp_db, "SYN-0001")
    text, _ = build_handover(b, set())
    assert "Ramipril" not in text and "None selected or none documented." in text
    text2, _ = build_handover(b, {"MED-0001"})
    assert "Ramipril" in text2 and "Amlodipine" not in text2


# ---- FHIR ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("pid", PIDS)
def test_bundle_passes_simplified_validation(tmp_db, pid):
    full = fhir_mapping.build_bundle(bundle(tmp_db, pid))
    json.dumps(full)
    assert full["resourceType"] == "Bundle"
    assert fhir_mapping.validate_bundle(full) == {}
    assert full["entry"][0]["resource"]["meta"]["tag"][0]["code"] == "HTEST"


def test_fhir_missing_data_not_invented(tmp_db):
    b = bundle(tmp_db, "SYN-0003")
    items = {i["record_id"]: i for i in fhir_mapping.build_resources(b)}
    nounit = [i for i in items.values() if i["table"] == "observations" and any("Unit not recorded" in m for m in i["issues"])][0]
    assert "unit" not in nounit["resource"]["valueQuantity"]
    nodate = [i for i in items.values() if i["table"] == "observations" and "effectiveDateTime" not in i["resource"]][0]
    assert any("No effective date" in m for m in nodate["issues"])
    noval = [i for i in items.values() if i["table"] == "observations" and "dataAbsentReason" in i["resource"]]
    assert noval


def test_source_flag_preserved_in_fhir(tmp_db):
    items = fhir_mapping.build_resources(bundle(tmp_db, "SYN-0001"))
    flagged = [i["resource"] for i in items if i["table"] == "observations" and "interpretation" in i["resource"]]
    assert flagged and flagged[0]["interpretation"][0]["text"].startswith("Flag as supplied by the source")


def test_validator_catches_problems():
    assert fhir_mapping.validate_resource({"resourceType": "Observation", "id": "x", "status": "bogus", "code": {}, "subject": {}})
    assert fhir_mapping.validate_resource({"resourceType": "Nope"})


# ---- data quality --------------------------------------------------------------------------------
def checks(tmp_db, pid):
    return set(data_quality.audit(bundle(tmp_db, pid), include_mapping=False)["check"])


def test_quality_demo_patients(tmp_db):
    c3 = checks(tmp_db, "SYN-0003")
    assert {"Missing date", "Missing unit", "Missing value", "Duplicate record", "Incomplete medication information", "Inconsistent terminology"} <= c3
    c6 = checks(tmp_db, "SYN-0006")
    assert {"Missing source", "Conflicting entries", "Inconsistent terminology"} <= c6
    assert "Potentially outdated medication record" in checks(tmp_db, "SYN-0002")
    assert checks(tmp_db, "SYN-0005") == set()


def test_dose_change_is_not_a_conflict(tmp_db):
    f = data_quality.audit(bundle(tmp_db, "SYN-0001"), include_mapping=False)
    assert "Conflicting entries" not in set(f["check"])


def test_normalisation_keeps_original(tmp_db):
    b = bundle(tmp_db, "SYN-0006")
    log = normalisation_log(b)
    assert {"HTN", "High blood pressure", "Type 2 DM"} <= set(log["original_source_text"])
    assert "HTN" in set(b["conditions"]["display"])            # source untouched


def test_report_export(tmp_db):
    b = bundle(tmp_db, "SYN-0006")
    md = data_quality.report_markdown(b["patients"].iloc[0].to_dict(), data_quality.audit(b), b)
    assert "SYNTHETIC" in md and "Normalisation log" in md


# ---- UI smoke tests ------------------------------------------------------------------------------
PAGES = ["Overview", "Patient Timeline", "Clinical Trends", "Clinical Summary", "Handover Builder", "Data & Interoperability", "About CareFlow"]


@pytest.mark.parametrize("pid", ["SYN-0001", "SYN-0003", "SYN-0006"])
@pytest.mark.parametrize("page", PAGES)
def test_every_page_renders(page, pid):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.selectbox(key="patient_id").set_value(pid)
    at.sidebar.radio(key="nav").set_value(page)
    at.run()
    assert not at.exception, [e.value for e in at.exception]


def test_handover_generation_flow():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio(key="nav").set_value("Handover Builder")
    at.run()
    at.button(key="ho_gen_SYN-0001").click().run()
    assert not at.exception
    assert "HANDOVER DRAFT" in at.session_state["ho_text_SYN-0001"]
    assert at.text_area(key="ho_edit_SYN-0001").value.startswith("CAREFLOW HANDOVER DRAFT")
    at.text_area(key="ho_edit_SYN-0001").set_value("edited by clinician").run()
    assert at.session_state["ho_edit_SYN-0001"] == "edited by clinician"


def test_dataset_reset_button():
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.button(key="reset_btn").click().run()
    assert not at.exception
    assert "Dataset regenerated" in at.session_state["reset_msg"]
