"""Google Sheets integration — authenticate and upload daily summary data."""

import json

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_NAME = "Daily Summary"


def _get_gsheets_client() -> gspread.Client:
    """Authenticate via service account from st.secrets["gsheets"]."""
    gsheets_config = st.secrets["gsheets"]
    sa_info = gsheets_config["service_account_info"]

    if isinstance(sa_info, str):
        sa_info = json.loads(sa_info)

    credentials = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    return gspread.authorize(credentials)


def upload_daily_summary(summary_df: pd.DataFrame, spreadsheet_id: str) -> None:
    """
    Upload daily summary DataFrame to Google Sheets.

    Creates worksheet if needed. Replaces all data with the current summary.
    """
    if summary_df.empty:
        return

    client = _get_gsheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    # Get or create worksheet
    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=SHEET_NAME,
            rows=str(len(summary_df) + 1),
            cols="9",
        )

    # Prepare data
    upload_df = summary_df.copy()

    # Ensure date is string
    if "date" in upload_df.columns:
        upload_df["date"] = pd.to_datetime(upload_df["date"]).dt.strftime("%Y-%m-%d")

    # Rename columns for the sheet
    column_map = {
        "date": "Date",
        "product_name": "Product",
        "new_customer_count": "New_Customers",
        "sale_count": "New_Sales_Count",
        "sale_revenue": "New_Sales_Revenue",
        "refund_count": "Refund_Count",
        "refund_amount": "Refund_Amount",
        "renewal_count": "Renewal_Count",
        "renewal_revenue": "Renewal_Revenue",
    }
    upload_df = upload_df.rename(columns=column_map)

    # Select and order columns
    sheet_cols = list(column_map.values())
    available = [c for c in sheet_cols if c in upload_df.columns]
    upload_df = upload_df[available]

    # Clear and write
    worksheet.clear()
    worksheet.update(
        [upload_df.columns.tolist()] + upload_df.values.tolist(),
        value_input_option="USER_ENTERED",
    )


def upload_report(
    df: pd.DataFrame, spreadsheet_id: str, worksheet_name: str,
) -> str:
    """Upload a DataFrame to a Google Sheet worksheet and return the sheet URL.

    Creates the worksheet if it doesn't exist. Replaces all data.
    Returns the spreadsheet URL for Slack linking.
    """
    if df.empty:
        return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    client = _get_gsheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_name,
            rows=str(len(df) + 1),
            cols=str(len(df.columns)),
        )

    # Convert timestamps/dates to strings for JSON serialization
    upload_df = df.copy()
    for col in upload_df.columns:
        if pd.api.types.is_datetime64_any_dtype(upload_df[col]):
            upload_df[col] = upload_df[col].dt.strftime("%Y-%m-%d %H:%M:%S")

    upload_df = upload_df.fillna("")

    worksheet.clear()
    worksheet.update(
        [upload_df.columns.tolist()] + upload_df.values.tolist(),
        value_input_option="USER_ENTERED",
    )

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
