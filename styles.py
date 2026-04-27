"""Global styles and Plotly chart theme for SamCart Analytics Dashboard.

Aesthetic: "Electric Ledger" — Bloomberg Terminal meets Figma dark mode.
Display: Bebas Neue (condensed, all-caps). Data: IBM Plex Mono.
"""

import plotly.io as pio
import streamlit as st

# Chart color sequence — bold, high-contrast, optimized for #07080E background
CHART_COLORS = [
    "#B8FF57",  # electric lime
    "#00D4FF",  # electric cyan
    "#FF4D6D",  # coral
    "#9D6FFF",  # purple
    "#FFB547",  # amber
    "#FF6B35",  # orange
    "#00FFB3",  # mint
    "#FF3CAC",  # hot pink
]

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=IBM+Plex+Mono:ital,wght@0,300;0,400;0,500;0,600;1,400&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

/* ── Dot-grid background on main app ── */
.stApp {
    background-color: #07080E !important;
    background-image: radial-gradient(circle, rgba(26,29,46,0.8) 1px, transparent 1px) !important;
    background-size: 28px 28px !important;
}

/* ── Page titles — Bebas Neue, massive ── */
[data-testid="stAppViewContainer"] h1 {
    font-family: 'Bebas Neue', sans-serif !important;
    font-size: 3.2rem !important;
    letter-spacing: 0.06em !important;
    text-transform: uppercase;
    color: #E8ECF8 !important;
    line-height: 1 !important;
}

/* ── Subheaders — mono, small-caps treatment ── */
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3 {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.72rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.15em !important;
    text-transform: uppercase !important;
    color: #B8FF57 !important;
    border-bottom: 1px solid #1A1D2E;
    padding-bottom: 8px;
    margin-bottom: 16px;
}

/* ── Body text ── */
html, body, [data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] span,
[data-testid="stAppViewContainer"] div {
    font-family: 'IBM Plex Mono', monospace;
}

/* ── st.metric cards ── */
[data-testid="stMetric"] {
    background: #0D0F1A !important;
    border: 1px solid #1A1D2E !important;
    border-top: 3px solid #B8FF57 !important;
    border-radius: 4px !important;
    padding: 20px 18px 16px !important;
    position: relative;
    overflow: hidden;
}

[data-testid="stMetricLabel"] p,
[data-testid="stMetricLabel"] span,
[data-testid="stMetricLabel"] div {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.60rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    color: #3A3F5C !important;
}

[data-testid="stMetricValue"] > div {
    font-family: 'Bebas Neue', sans-serif !important;
    font-size: 2.6rem !important;
    font-weight: 400 !important;
    letter-spacing: 0.04em !important;
    color: #E8ECF8 !important;
    line-height: 1.1 !important;
}

[data-testid="stMetricDelta"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.72rem !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #060709 !important;
    border-right: 1px solid #1A1D2E !important;
}

[data-testid="stSidebar"] h1 {
    font-family: 'Bebas Neue', sans-serif !important;
    font-size: 1.4rem !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
    color: #B8FF57 !important;
}

[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.60rem !important;
    letter-spacing: 0.18em !important;
    text-transform: uppercase !important;
    border-bottom: none !important;
    color: #B8FF57 !important;
}

/* ── Tabs ── */
[data-testid="stTabs"] button[role="tab"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.72rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.12em !important;
    text-transform: uppercase !important;
}

/* ── DataFrames ── */
[data-testid="stDataFrame"] {
    border: 1px solid #1A1D2E !important;
    border-top: 2px solid #B8FF57 !important;
    border-radius: 0 !important;
}

/* ── Buttons ── */
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.72rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.10em !important;
    text-transform: uppercase !important;
    border-radius: 2px !important;
    border: 1px solid #B8FF57 !important;
    color: #B8FF57 !important;
    background: transparent !important;
    transition: all 0.12s ease !important;
}

[data-testid="stButton"] > button:hover,
[data-testid="stDownloadButton"] > button:hover {
    background: #B8FF57 !important;
    color: #07080E !important;
}

/* ── Primary buttons (filled) ── */
[data-testid="stButton"] > button[kind="primary"] {
    background: #B8FF57 !important;
    color: #07080E !important;
}

/* ── Caption text ── */
[data-testid="stCaptionContainer"] p,
[data-testid="stCaptionContainer"] span {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.68rem !important;
    color: #3A3F5C !important;
    letter-spacing: 0.04em !important;
}

/* ── Dividers ── */
hr {
    border-color: #1A1D2E !important;
}

/* ── Alerts ── */
[data-testid="stAlert"] {
    border-radius: 2px !important;
    border-left: 3px solid #B8FF57 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.78rem !important;
}

[data-testid="stAlert"][data-type="success"] {
    border-left-color: #B8FF57 !important;
}
[data-testid="stAlert"][data-type="error"] {
    border-left-color: #FF4D6D !important;
}

/* ── Expanders ── */
[data-testid="stExpander"] {
    border: 1px solid #1A1D2E !important;
    border-radius: 0 !important;
    border-left: 3px solid #1A1D2E !important;
}

/* ── Input widget labels ── */
[data-testid="stSelectbox"] label,
[data-testid="stMultiSelect"] label,
[data-testid="stDateInput"] label,
[data-testid="stSlider"] label,
[data-testid="stRadio"] label {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.68rem !important;
    letter-spacing: 0.10em !important;
    text-transform: uppercase !important;
    color: #3A3F5C !important;
}

/* ── Column gaps ── */
[data-testid="stHorizontalBlock"] {
    gap: 0.75rem !important;
}

/* ── Custom metric card HTML classes (used in app.py) ── */
.mc-grid {
    display: grid;
    gap: 0.75rem;
}
.mc {
    background: #0D0F1A;
    border: 1px solid #1A1D2E;
    border-top: 3px solid #B8FF57;
    padding: 18px 18px 14px;
    position: relative;
}
.mc-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.60rem;
    font-weight: 500;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #3A3F5C;
    margin-bottom: 8px;
}
.mc-value {
    font-family: 'Bebas Neue', sans-serif;
    font-size: 2.4rem;
    color: #E8ECF8;
    line-height: 1;
    letter-spacing: 0.04em;
}
.mc-delta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem;
    margin-top: 6px;
    letter-spacing: 0.04em;
}
.mc-delta.pos { color: #B8FF57; }
.mc-delta.neg { color: #FF4D6D; }
.mc-delta.neu { color: #3A3F5C; }
.mc-help {
    position: absolute;
    top: 12px; right: 12px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.60rem;
    color: #3A3F5C;
    cursor: help;
    width: 14px; height: 14px;
    border: 1px solid #3A3F5C;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
}
</style>
"""

_CHART_TEMPLATE = {
    "layout": {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(13,15,26,0.6)",
        "colorway": CHART_COLORS,
        "font": {"family": "IBM Plex Mono, monospace", "color": "#E8ECF8", "size": 11},
        "title": {
            "font": {
                "family": "Bebas Neue, sans-serif",
                "color": "#E8ECF8",
                "size": 18,
            },
        },
        "xaxis": {
            "gridcolor": "#1A1D2E",
            "linecolor": "#1A1D2E",
            "tickfont": {"color": "#3A3F5C", "size": 10, "family": "IBM Plex Mono"},
            "title": {"font": {"color": "#3A3F5C", "family": "IBM Plex Mono"}},
            "zeroline": False,
        },
        "yaxis": {
            "gridcolor": "#1A1D2E",
            "linecolor": "#1A1D2E",
            "tickfont": {"color": "#3A3F5C", "size": 10, "family": "IBM Plex Mono"},
            "title": {"font": {"color": "#3A3F5C", "family": "IBM Plex Mono"}},
            "zeroline": False,
        },
        "legend": {
            "bgcolor": "rgba(13,15,26,0.9)",
            "bordercolor": "#1A1D2E",
            "borderwidth": 1,
            "font": {"color": "#3A3F5C", "size": 10, "family": "IBM Plex Mono"},
        },
        "hoverlabel": {
            "bgcolor": "#0D0F1A",
            "bordercolor": "#B8FF57",
            "font": {"family": "IBM Plex Mono", "color": "#E8ECF8", "size": 11},
        },
        "margin": {"l": 48, "r": 20, "t": 48, "b": 44},
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
