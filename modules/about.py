"""About CareFlow: purpose, research framing, evaluation ideas and safety statements."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import ui

EVALUATION = [
    ("Time to retrieve selected information", "Task timing (seconds) for set retrieval questions, compared with the usual record system.", "Quantitative"),
    ("Completeness of information retrieval", "Proportion of pre-defined items found by each participant.", "Quantitative"),
    ("Accuracy of generated summaries", "Statement-by-statement comparison with source records by clinician reviewers.", "Quantitative"),
    ("Number of omissions", "Count of relevant documented items missing from summaries or handovers.", "Quantitative"),
    ("Source traceability", "Can participants reach the correct source record for a given statement, and how quickly?", "Mixed"),
    ("User satisfaction", "Post-task satisfaction rating.", "Questionnaire"),
    ("Perceived cognitive workload", "A validated workload instrument such as NASA-TLX.", "Questionnaire"),
    ("Usability", "A validated usability scale such as the System Usability Scale (SUS).", "Questionnaire"),
    ("Trust in the interface", "Trust-in-automation questionnaire plus interview prompts.", "Mixed"),
    ("Ease of identifying missing information", "Seeded gaps in test records; proportion detected and time to detect.", "Quantitative"),
]


def render() -> None:
    ui.page_header("About CareFlow", "Clinical Timeline & Handover Intelligence")
    ui.synthetic_banner()
    st.info(ui.DISCLAIMER)

    st.markdown("### Problem statement")
    st.write("Patient information fragmentation can create challenges in record retrieval, longitudinal review, information synthesis and clinical handover.")
    st.markdown("### Project objective")
    st.write("Explore a structured, traceable and clinician-centred interface for longitudinal patient information and handover preparation.")
    st.markdown("### Potential research question")
    st.markdown("> Can a structured, traceable clinical timeline and handover preparation tool improve clinicians' information retrieval efficiency "
                "and perceived usability while maintaining the completeness and accuracy of clinical information?")

    st.markdown("### Potential evaluation measures")
    st.caption("These are proposed research measures. CareFlow has not been evaluated, and no benefit has been demonstrated.")
    st.dataframe(pd.DataFrame(EVALUATION, columns=["Measure", "Possible approach", "Type"]), hide_index=True, width="stretch")

    st.markdown("### Requirements for a future study")
    st.markdown("- Appropriate **ethical review** and institutional approval before involving participants or any real data.\n"
                "- **Participant consent** where applicable.\n"
                "- A suitable **study design** (for example a within-subject comparison with counterbalanced tasks) and a pre-specified analysis plan.\n"
                "- Involvement of **clinical stakeholders** in task design, safety review and interpretation.\n"
                "- A separate data-protection assessment before any non-synthetic data is used.")

    st.markdown("### Responsible AI and safety design")
    st.markdown("- **Transparency:** content is labelled as source, normalised, derived or generated; every summary statement links to its records.\n"
                "- **Human oversight:** drafts are editable, carry a verification warning and a sign-off block, and are never presented as verified.\n"
                "- **No clinical inference:** no diagnosis, no treatment advice, no stable/unstable labels, no urgency or severity scores, no invented reference ranges.\n"
                "- **Missing data is shown, not filled in:** gaps and conflicts are reported in the data quality audit.\n"
                "- **Data protection:** synthetic data only; runs locally; no external services; no API keys.")
    st.markdown("### What is real and what is simulated")
    st.markdown("- **Functional:** SQLite storage, filtering and search, charts, rule-based summary, handover builder, FHIR-style JSON export, simplified structural checks, data quality audit, dataset reset.\n"
                "- **Simulated / illustrative:** all patient data; the terminology codes; the FHIR mapping (not conformance-tested).\n"
                "- **Not implemented:** any AI model, PDF export, user authentication, real EHR integration.")
    st.markdown("### Colour and label key")
    ui.layer_legend()
