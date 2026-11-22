"""Shared look-and-feel: CSS, badges and small HTML components."""
from __future__ import annotations

import html

import streamlit as st

NAVY = "#12284C"
TEAL = "#0F766E"
BLUE = "#5B7DB1"
AMBER = "#B45309"
RED = "#B42318"

DISCLAIMER = ("CareFlow is an educational and research prototype using synthetic data. It is not a medical device, electronic health "
              "record replacement or clinical decision-making tool. Information displayed is not intended to diagnose, treat or manage "
              "medical conditions. Generated summaries and handovers require human review and verification. The application has not "
              "been clinically validated.")
DRAFT_WARNING = ("AI-assisted or system-generated handovers are drafts. Review the original clinical records, verify the content and "
                 "confirm completeness before clinical use.")

CSS = f"""
<style>
html, body, [class*="css"] {{ font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif; }}
.block-container {{ padding-top: 1.4rem; max-width: 1280px; }}
h1, h2, h3, h4 {{ color: {NAVY}; letter-spacing: -0.01em; }}
section[data-testid="stSidebar"] {{ background: #F3F6FA; border-right: 1px solid #E2E8F0; }}
.cf-brand {{ font-size: 1.45rem; font-weight: 700; color: {NAVY}; margin: 0; }}
.cf-brand span {{ color: {TEAL}; }}
.cf-tag {{ font-size: .78rem; color: #52627A; margin-bottom: .6rem; }}
.cf-card {{ background: #fff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px 16px;
           box-shadow: 0 1px 2px rgba(16,24,40,.04); margin-bottom: 10px; }}
.cf-metric-label {{ font-size: .78rem; color: #52627A; text-transform: uppercase; letter-spacing: .04em; }}
.cf-metric-value {{ font-size: 1.7rem; font-weight: 700; color: {NAVY}; line-height: 1.2; }}
.cf-metric-sub {{ font-size: .78rem; color: #6B7A90; }}
.cf-badge {{ display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: .72rem; font-weight: 600;
            border: 1px solid; margin-right: 4px; white-space: nowrap; }}
.cf-source {{ color: {TEAL}; border-color: #99D5CF; background: #ECF8F6; }}
.cf-generated {{ color: #3D4E9A; border-color: #B7C2EC; background: #EFF2FC; }}
.cf-derived {{ color: #1F5F8B; border-color: #A9CBE6; background: #EEF6FB; }}
.cf-normalised {{ color: #6B4E9A; border-color: #CDBBE8; background: #F5F0FB; }}
.cf-missing {{ color: {AMBER}; border-color: #F1CFA0; background: #FEF6E7; }}
.cf-alert {{ color: {RED}; border-color: #F2B8B3; background: #FEF0EF; }}
.cf-banner {{ border-left: 4px solid {AMBER}; background: #FEF6E7; padding: 10px 14px; border-radius: 6px; color: #5A3A0A; margin: 6px 0 12px; }}
.cf-synth {{ border-left: 4px solid {BLUE}; background: #EEF3FA; padding: 8px 12px; border-radius: 6px; color: #23406B; font-size: .85rem; margin-bottom: 10px; }}
.cf-event {{ border-left: 3px solid #CBD5E1; padding: 2px 0 2px 12px; margin-bottom: 8px; }}
.cf-event-date {{ font-size: .78rem; color: #6B7A90; }}
.cf-muted {{ color: #6B7A90; font-size: .85rem; }}
.cf-rec-title {{ font-weight: 600; color: {NAVY}; }}
@media (max-width: 900px) {{ .block-container {{ padding-left: 1rem; padding-right: 1rem; }} .cf-metric-value {{ font-size: 1.3rem; }} }}
</style>
"""

LAYERS = {
    "source": ("SOURCE DATA", "cf-source"),
    "normalised": ("NORMALISED", "cf-normalised"),
    "derived": ("DERIVED", "cf-derived"),
    "generated": ("GENERATED TEXT", "cf-generated"),
    "missing": ("NOT RECORDED", "cf-missing"),
    "alert": ("REVIEW", "cf-alert"),
}


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def badge(kind: str, text: str | None = None) -> str:
    label, cls = LAYERS[kind]
    return f'<span class="cf-badge {cls}">{html.escape(text or label)}</span>'


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def metric_card(label: str, value: str, sub: str | None) -> None:
    st.markdown(f'<div class="cf-card"><div class="cf-metric-label">{esc(label)}</div>'
                f'<div class="cf-metric-value">{esc(value)}</div>'
                f'<div class="cf-metric-sub">{esc(sub) if sub else "&nbsp;"}</div></div>', unsafe_allow_html=True)


def synthetic_banner() -> None:
    st.markdown('<div class="cf-synth"><b>Synthetic data.</b> All patients are fictional and were generated for this prototype. '
                'No real patient information is used.</div>', unsafe_allow_html=True)


def draft_banner() -> None:
    st.markdown(f'<div class="cf-banner"><b>Draft only.</b> {esc(DRAFT_WARNING)}</div>', unsafe_allow_html=True)


def layer_legend() -> None:
    st.markdown(" ".join(badge(k) for k in ("source", "normalised", "derived", "generated", "missing", "alert")), unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None) -> None:
    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)
