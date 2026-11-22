"""Clinical trends: interactive charts of recorded observations. No interpretation is added."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from utils import ui
from utils.data_processing import fmt_date, fmt_num, is_missing, ref_range_str, source_label

BP_LABEL = "Blood pressure (systolic and diastolic)"
SYS, DIA = "Systolic blood pressure", "Diastolic blood pressure"


def observation_options(obs: pd.DataFrame) -> list[str]:
    names = sorted(obs.dropna(subset=["value_num", "effective_date"])["display"].unique())
    if SYS in names and DIA in names:
        names = [n for n in names if n not in (SYS, DIA)]
        names.insert(0, BP_LABEL)
    return names


def series(obs: pd.DataFrame, name: str) -> pd.DataFrame:
    """Rows with a value and a date for one observation, oldest first."""
    df = obs[(obs["display"] == name)].dropna(subset=["value_num", "effective_date"]).copy()
    df["effective_date"] = pd.to_datetime(df["effective_date"])
    return df.sort_values("effective_date")


def describe(df: pd.DataFrame) -> list[str]:
    """Neutral, factual description of a series (DERIVED). Never interprets values."""
    if df.empty:
        return ["No measurements with both a value and a date are recorded."]
    unit = df["unit"].dropna().unique()
    u = f" {unit[0]}" if len(unit) == 1 else ""
    lines = [f"{len(df)} measurement(s) recorded between {fmt_date(df['effective_date'].min())} and {fmt_date(df['effective_date'].max())}."]
    first, last = df.iloc[0], df.iloc[-1]
    if len(df) >= 3:
        lines.append(f"First recorded value {fmt_num(first['value_num'])}{u} ({fmt_date(first['effective_date'])}); latest {fmt_num(last['value_num'])}{u} ({fmt_date(last['effective_date'])}).")
        hi, lo = df.loc[df["value_num"].idxmax()], df.loc[df["value_num"].idxmin()]
        lines.append(f"Highest recorded {fmt_num(hi['value_num'])}{u} ({fmt_date(hi['effective_date'])}); lowest {fmt_num(lo['value_num'])}{u} ({fmt_date(lo['effective_date'])}).")
        if len(unit) > 1:
            lines.append("More than one unit is recorded; values are not converted, so comparisons across units are not made.")
    else:
        lines.append(f"Only {len(df)} measurement(s) recorded: there is insufficient data to describe a trend.")
    return lines


def _ref_band(fig: go.Figure, df: pd.DataFrame) -> str | None:
    ranges = df[["ref_low", "ref_high"]].drop_duplicates()
    ranges = ranges.dropna(how="all")
    if ranges.empty:
        return "No reference range is recorded in the source data for this observation, so values are shown without any normal/abnormal comparison."
    if len(ranges) > 1:
        return "The reference range differs between records; see the table. No band is drawn."
    lo, hi = ranges.iloc[0]["ref_low"], ranges.iloc[0]["ref_high"]
    y0 = lo if not pd.isna(lo) else df["value_num"].min() - (df["value_num"].max() - df["value_num"].min() + 1)
    y1 = hi if not pd.isna(hi) else df["value_num"].max() + (df["value_num"].max() - df["value_num"].min() + 1)
    fig.add_hrect(y0=y0, y1=y1, fillcolor="#0F766E", opacity=0.08, line_width=0,
                  annotation_text="Reference range (from source record)", annotation_position="top left", annotation_font_size=11)
    return None


def build_figure(obs: pd.DataFrame, name: str) -> tuple[go.Figure, pd.DataFrame, str | None]:
    fig = go.Figure()
    note = None
    if name == BP_LABEL:
        parts = [series(obs, SYS), series(obs, DIA)]
        for df, label, colour in zip(parts, ["Systolic", "Diastolic"], ["#12284C", "#5B7DB1"]):
            fig.add_trace(go.Scatter(x=df["effective_date"], y=df["value_num"], mode="lines+markers", name=f"{label} (mmHg)",
                                     line=dict(color=colour, width=2), marker=dict(size=8),
                                     customdata=df[["observation_id", "source_system"]].fillna("not recorded"),
                                     hovertemplate="%{x|%d %b %Y}<br>%{y} mmHg<br>%{customdata[0]} · %{customdata[1]}<extra>" + label + "</extra>"))
        data = pd.concat(parts).sort_values("effective_date")
        note = "No reference range is recorded in the source data for blood pressure, so values are shown without any normal/abnormal comparison."
        fig.update_yaxes(title="mmHg")
    else:
        data = series(obs, name)
        units = list(data["unit"].fillna("unit not recorded").unique())
        colours = ["#0F766E", "#5B7DB1", "#8C6D9C"]
        for i, u in enumerate(units):
            sub = data[data["unit"].fillna("unit not recorded") == u]
            fig.add_trace(go.Scatter(x=sub["effective_date"], y=sub["value_num"], mode="lines+markers", name=u,
                                     line=dict(color=colours[i % 3], width=2), marker=dict(size=8),
                                     customdata=sub[["observation_id", "source_system", "flag"]].fillna("none"),
                                     hovertemplate="%{x|%d %b %Y}<br>%{y} " + u + "<br>%{customdata[0]} · %{customdata[1]}<br>Source flag: %{customdata[2]}<extra></extra>"))
        flagged = data[data["flag"].notna()]
        if not flagged.empty:
            fig.add_trace(go.Scatter(x=flagged["effective_date"], y=flagged["value_num"], mode="markers", name="Flag supplied by source",
                                     marker=dict(size=13, color="rgba(0,0,0,0)", line=dict(color="#B45309", width=2)), hoverinfo="skip"))
        if len(units) == 1:
            note = _ref_band(fig, data)
            fig.update_yaxes(title=units[0])
        else:
            note = "This observation is recorded in more than one unit. Values are plotted per unit and have NOT been converted."
    fig.update_layout(height=380, margin=dict(l=0, r=0, t=20, b=0), plot_bgcolor="white", legend=dict(orientation="h", y=-0.15), hovermode="closest")
    fig.update_xaxes(showgrid=True, gridcolor="#EEF2F6")
    fig.update_yaxes(showgrid=True, gridcolor="#EEF2F6")
    return fig, data, note


def render(patient: dict, bundle: dict) -> None:
    ui.page_header("Clinical Trends", "Recorded observations over time. Only observations present in this patient's data are listed.")
    ui.synthetic_banner()
    obs = bundle["observations"]
    options = observation_options(obs)
    if not options:
        st.info("No observations with both a value and a date are recorded for this patient.")
        return
    name = st.selectbox("Observation", options, key=f"tr_obs_{patient['patient_id']}")
    fig, data, note = build_figure(obs, name)
    parts = [series(obs, SYS), series(obs, DIA)] if name == BP_LABEL else [data]
    st.plotly_chart(fig, width="stretch")
    if note:
        st.markdown(ui.badge("missing", "REFERENCE RANGE") + " " + note, unsafe_allow_html=True)
    st.markdown("#### What the records show " + ui.badge("derived"), unsafe_allow_html=True)
    for df, label in zip(parts, ["Systolic", "Diastolic"] if name == BP_LABEL else [name]):
        for line in describe(df):
            st.markdown(f"- {'**' + label + ':** ' if name == BP_LABEL else ''}{line}")
    skipped = obs[(obs["display"].isin([SYS, DIA] if name == BP_LABEL else [name]))]
    skipped = skipped[skipped["value_num"].isna() | skipped["effective_date"].isna()]
    if not skipped.empty:
        st.markdown(ui.badge("missing") + f" {len(skipped)} record(s) for this observation have no value or no date and are not plotted: "
                    + ", ".join(skipped["observation_id"]), unsafe_allow_html=True)
    st.markdown("#### Underlying values " + ui.badge("source"), unsafe_allow_html=True)
    table = pd.DataFrame({
        "Date": data["effective_date"].dt.strftime("%d %b %Y"),
        "Observation": data["display"],
        "Value": data["value_num"], "Unit": data["unit"].fillna("not recorded"),
        "Reference range (source)": [ref_range_str(r) or "not in source" for _, r in data.iterrows()],
        "Flag (source)": data["flag"].fillna(""),
        "Record": data["observation_id"],
        "Source": [source_label(r) for _, r in data.iterrows()],
    })
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption("Flags and reference ranges are shown exactly as supplied by the source system. CareFlow does not calculate normal/abnormal.")
    ids = list(table["Record"])
    pick = st.selectbox("Inspect a source record", ids, key=f"tr_src_{patient['patient_id']}")
    from modules.timeline import render_record_detail
    with st.expander("Source record", expanded=True):
        render_record_detail(pick, bundle)
