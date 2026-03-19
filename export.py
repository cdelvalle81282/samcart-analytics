"""Excel/CSV export with formatting, PII toggle, and auto-cleanup."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

EXPORTS_DIR = Path("exports")

# Columns considered PII — excluded by default
PII_COLUMNS = {"phone", "billing_city", "billing_state", "billing_country", "email", "customer_email", "first_name", "last_name"}


def _ensure_exports_dir():
    EXPORTS_DIR.mkdir(exist_ok=True)


def _strip_pii(df: pd.DataFrame, include_pii: bool) -> pd.DataFrame:
    """Remove PII columns if include_pii is False."""
    if include_pii:
        return df
    cols_to_drop = [c for c in df.columns if c in PII_COLUMNS]
    return df.drop(columns=cols_to_drop, errors="ignore")


def export_to_excel(df: pd.DataFrame, sheet_name: str = "Data", include_pii: bool = False) -> bytes:
    """
    Format DataFrame as Excel bytes for st.download_button.

    Returns bytes (not a file path) for Streamlit download.
    """
    df = _strip_pii(df, include_pii)
    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]
        # Auto-fit column widths
        for col_idx, col_name in enumerate(df.columns, 1):
            max_len = max(
                len(str(col_name)),
                df[col_name].astype(str).str.len().max() if not df.empty else 0,
            )
            ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 2, 50)
        # Format currency columns
        for col_idx, col_name in enumerate(df.columns, 1):
            if col_name in ("total", "amount", "total_spend", "total_revenue", "avg_order_value", "price", "estimated_ltv"):
                for row_idx in range(2, len(df) + 2):
                    ws.cell(row=row_idx, column=col_idx).number_format = '$#,##0.00'
    buf.seek(0)
    return buf.getvalue()


def export_to_csv(df: pd.DataFrame, include_pii: bool = False) -> bytes:
    """Format DataFrame as CSV bytes for st.download_button."""
    df = _strip_pii(df, include_pii)
    return df.to_csv(index=False).encode("utf-8")


def cleanup_old_exports(max_age_days: int = 7) -> int:
    """Delete export files older than max_age_days. Returns count deleted."""
    if not EXPORTS_DIR.exists():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    deleted = 0
    for f in EXPORTS_DIR.iterdir():
        if f.is_file():
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                deleted += 1
    return deleted


def render_export_buttons(df: pd.DataFrame, filename_base: str, key_prefix: str = ""):
    """Render download buttons for Excel and CSV with optional PII toggle."""
    if df.empty:
        return

    # Defense-in-depth: strip anything that looks like PII from filename
    if "@" in filename_base:
        filename_base = "export"

    col1, col2, col3 = st.columns([1, 1, 1])

    include_pii = col3.checkbox(
        "Include PII",
        value=False,
        key=f"{key_prefix}_include_pii",
        help="Include phone, email, and address columns in export",
    )

    excel_data = export_to_excel(df, include_pii=include_pii)
    col1.download_button(
        label="Download Excel",
        data=excel_data,
        file_name=f"{filename_base}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{key_prefix}_xlsx",
    )

    csv_data = export_to_csv(df, include_pii=include_pii)
    col2.download_button(
        label="Download CSV",
        data=csv_data,
        file_name=f"{filename_base}.csv",
        mime="text/csv",
        key=f"{key_prefix}_csv",
    )
