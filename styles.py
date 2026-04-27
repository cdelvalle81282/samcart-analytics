"""Global styles and Plotly chart theme for SamCart Analytics Dashboard."""

import plotly.io as pio
import streamlit as st

# Chart color sequence — works well on dark backgrounds
CHART_COLORS = [
    "#4F90F0",  # blue
    "#10B981",  # emerald
    "#F59E0B",  # amber
    "#EF4444",  # red
    "#8B5CF6",  # purple
    "#EC4899",  # pink
    "#06B6D4",  # cyan
    "#F97316",  # orange
]

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap');

/* ── Base typography ── */
html, body,
[data-testid="stAppViewContainer"],
[data-testid="stSidebar"] {
    font-family: 'IBM Plex Sans', sans-serif !important;
}

/* ── Page title ── */
[data-testid="stAppViewContainer"] h1 {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 1.55rem !important;
    font-weight: 600;
    letter-spacing: -0.015em;
    margin-bottom: 0.15rem;
}

/* ── Subheaders ── */
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3 {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 600;
    letter-spacing: -0.01em;
}

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: #161C2A;
    border: 1px solid #253047;
    border-radius: 10px;
    padding: 18px 20px 16px !important;
    position: relative;
    overflow: hidden;
}

[data-testid="stMetric"]::after {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, #4F90F0 0%, #8B5CF6 100%);
    border-radius: 10px 10px 0 0;
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] span,
[data-testid="stMetricLabel"] div {
    font-size: 0.70rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    color: #7A8899 !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
}

[data-testid="stMetricValue"] > div {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 1.65rem !important;
    font-weight: 500 !important;
    letter-spacing: -0.02em !important;
    color: #E8EEF7 !important;
}

[data-testid="stMetricDelta"] {
    font-size: 0.78rem !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
}

/* ── Sidebar refinements ── */
[data-testid="stSidebar"] {
    border-right: 1px solid #1E2840 !important;
}

[data-testid="stSidebar"] h1 {
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.01em;
    color: #E8EEF7;
}

[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    font-size: 0.70rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.09em !important;
    text-transform: uppercase !important;
    color: #4F90F0 !important;
    margin-bottom: 0.4rem;
}

/* ── Caption / muted text ── */
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span {
    color: #5E6E85 !important;
    font-size: 0.76rem !important;
}

/* ── Tabs ── */
[data-testid="stTabs"] [data-testid="stTab"] p {
    font-size: 0.82rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] {
    border: 1px solid #253047 !important;
    border-radius: 8px !important;
    overflow: hidden;
}

/* ── Buttons ── */
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button {
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    letter-spacing: 0.02em !important;
    border-radius: 6px !important;
    transition: opacity 0.12s ease !important;
}

/* ── Dividers ── */
hr {
    border-color: #1E2840 !important;
    margin: 0.75rem 0 !important;
}

/* ── Horizontal block column gap ── */
[data-testid="stHorizontalBlock"] {
    gap: 0.85rem !important;
}

/* ── Info / warning / error alerts ── */
[data-testid="stAlert"] {
    border-radius: 8px !important;
    font-size: 0.85rem !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    border: 1px solid #253047 !important;
    border-radius: 8px !important;
}
</style>
"""

_CHART_TEMPLATE = {
    "layout": {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(22,28,42,0.55)",
        "colorway": CHART_COLORS,
        "font": {
            "family": "IBM Plex Sans, sans-serif",
            "color": "#E8EEF7",
            "size": 12,
        },
        "title": {
            "font": {"family": "IBM Plex Sans, sans-serif", "color": "#E8EEF7", "size": 14},
        },
        "xaxis": {
            "gridcolor": "#1E2840",
            "linecolor": "#253047",
            "tickfont": {"color": "#7A8899", "size": 11},
            "title": {"font": {"color": "#9AA5B4"}},
            "zeroline": False,
        },
        "yaxis": {
            "gridcolor": "#1E2840",
            "linecolor": "#253047",
            "tickfont": {"color": "#7A8899", "size": 11},
            "title": {"font": {"color": "#9AA5B4"}},
            "zeroline": False,
        },
        "legend": {
            "bgcolor": "rgba(22,28,42,0.8)",
            "bordercolor": "#253047",
            "borderwidth": 1,
            "font": {"color": "#9AA5B4", "size": 11},
        },
        "hoverlabel": {
            "bgcolor": "#1A2135",
            "bordercolor": "#4F90F0",
            "font": {"family": "IBM Plex Sans", "color": "#E8EEF7"},
        },
        "margin": {"l": 48, "r": 20, "t": 44, "b": 44},
    }
}

_theme_applied = False


def inject_styles() -> None:
    """Inject global CSS and activate the dark chart theme. Called once per page."""
    global _theme_applied
    st.markdown(_CSS, unsafe_allow_html=True)
    if not _theme_applied:
        pio.templates["samcart_dark"] = _CHART_TEMPLATE
        pio.templates.default = "plotly_dark+samcart_dark"
        _theme_applied = True
