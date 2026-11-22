"""Data & Interoperability: FHIR-inspired exploration, mapping table, data quality audit and dataset view."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from modules import data_quality
from utils import fhir_mapping, ui
from utils.data_processing import ID_COLUMN


def render(patient: dict, bundle: dict) -> None:
    ui.page_header("Data & Interoperability", "How the same records could be expressed with HL7 FHIR concepts, and how complete the data is.")
    ui.synthetic_banner()
    st.markdown('<div class="cf-banner"><b>Not FHIR-compliant.</b> This is a FHIR-inspired (R4) illustration. It has not been validated with the official HL7 '
                'validator, and CareFlow makes no conformance claim. The built-in check is a simplified structural demonstration.</div>', unsafe_allow_html=True)
    tabs = st.tabs(["FHIR explorer", "Mapping table", "Data quality audit", "Source dataset"])

    with tabs[0]:
        med_res = st.radio("Medication resource", ["MedicationRequest", "MedicationStatement"], horizontal=True, key="io_med",
                           help="The same medication records can be shown as prescriptions or as statements of medication use.")
        items = fhir_mapping.build_resources(bundle, med_res)
        types = sorted({i["resource"]["resourceType"] for i in items if i["resource"]})
        c1, c2 = st.columns([1, 2])
        rtype = c1.selectbox("Resource type", types, key="io_type")
        subset = [i for i in items if i["resource"] and i["resource"]["resourceType"] == rtype]
        labels = {f"{i['resource']['id']}": i for i in subset}
        rid = c2.selectbox("Record", list(labels), key=f"io_rec_{rtype}")
        item = labels[rid]
        col_json, col_info = st.columns([1.6, 1])
        with col_json:
            st.markdown("**FHIR-style JSON** " + ui.badge("derived", "MAPPED FROM SOURCE"), unsafe_allow_html=True)
            st.code(json.dumps(item["resource"], indent=2), language="json")
        with col_info:
            st.markdown("**Mapping limitations for this record**")
            if item["issues"]:
                for msg in item["issues"]:
                    st.markdown(f"- {msg}")
            else:
                st.success("No mapping limitations noted for this record.")
            probs = fhir_mapping.validate_resource(item["resource"])
            st.markdown("**Simplified structural check**")
            st.caption("Checks required elements, status codes and date formats only.")
            st.success("Passed the simplified checks.") if not probs else [st.error(p) for p in probs]
            st.markdown("**Source row**")
            table = item["table"]
            src = bundle[table]
            row = src[src[ID_COLUMN[table]] == item["record_id"]].iloc[0].dropna()
            st.dataframe(pd.DataFrame({"field": row.index, "value": row.astype(str).values}), hide_index=True, width="stretch")

        st.markdown("#### Export")
        full = fhir_mapping.build_bundle(bundle, med_res)
        problems = fhir_mapping.validate_bundle(full)
        c3, c4 = st.columns(2)
        c3.metric("Resources in bundle", len(full["entry"]))
        c4.metric("Resources failing simplified check", len(problems))
        if problems:
            st.dataframe(pd.DataFrame([{"resource": k, "problems": "; ".join(v)} for k, v in problems.items()]), hide_index=True)
        st.download_button("Download patient bundle (JSON)", json.dumps(full, indent=2), file_name=f"careflow_fhir_bundle_{patient['patient_id']}.json", mime="application/json")
        st.caption("Bundle type 'collection', FHIR R4 style. Resource ids are the CareFlow record ids. Tasks are not mapped.")

        unmapped = [i for i in items if i["issues"]]
        with st.expander(f"All mapping limitations across this patient's records ({len(unmapped)} records)"):
            st.dataframe(pd.DataFrame([{"table": i["table"], "record": i["record_id"], "limitations": " | ".join(i["issues"])} for i in unmapped]),
                         hide_index=True, width="stretch")

    with tabs[1]:
        st.markdown("Illustrative mapping between CareFlow record types and HL7 FHIR R4 resource concepts.")
        st.dataframe(fhir_mapping.mapping_table(), hide_index=True, width="stretch")
        st.markdown("**Known limitations of this mapping**")
        st.markdown("- Medications are free text (no RxNorm / dm+d coding); dosage is not split into structured dose and timing.\n"
                    "- Several required FHIR elements (e.g. MedicationRequest.intent, DiagnosticReport.status) are not held in the source and are set to documented placeholder values.\n"
                    "- Blood pressure is stored as two separate Observations rather than a panel with components.\n"
                    "- Practitioners, organisations and locations are not modelled; authors are role text only.\n"
                    "- LOINC and SNOMED CT codes are illustrative and have not been checked against a terminology server.")

    with tabs[2]:
        data_quality.render_audit(patient, bundle)

    with tabs[3]:
        st.markdown("Source records exactly as stored in the local SQLite database " + ui.badge("source"), unsafe_allow_html=True)
        table = st.selectbox("Table", [t for t in bundle if t != "patients"], key="io_table")
        st.dataframe(bundle[table], hide_index=True, width="stretch")
        st.caption("Empty cells mean 'not recorded in the source'. CareFlow does not fill them in.")
