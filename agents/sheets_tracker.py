"""
Google Sheets Tracker Agent
Logs all job applications to a centralized Google Sheet.
Columns: Date Applied, Job Title, Company, Location, Job URL,
         Status, Resume Version, Resume Folder, Job Source, Notes
"""
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

from config import (
    GOOGLE_CREDENTIALS_PATH,
    GOOGLE_SHEET_NAME,
    SHEET_COLUMNS,
)
from agents.job_fetcher import JobListing
from utils.logger import get_logger

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_sheet() -> gspread.Worksheet | None:
    """Authenticate and return the first worksheet of the tracker sheet."""
    creds_path = Path(GOOGLE_CREDENTIALS_PATH)
    if not creds_path.exists():
        logger.warning(
            f"Google credentials not found at {creds_path}. "
            "Sheets tracking disabled. See README for setup instructions."
        )
        return None

    try:
        creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
        gc = gspread.authorize(creds)
        try:
            spreadsheet = gc.open(GOOGLE_SHEET_NAME)
        except gspread.SpreadsheetNotFound:
            spreadsheet = gc.create(GOOGLE_SHEET_NAME)
            logger.info(f"Created new Google Sheet: '{GOOGLE_SHEET_NAME}'")

        sheet = spreadsheet.sheet1
        # Ensure headers exist
        if not sheet.row_values(1):
            sheet.append_row(SHEET_COLUMNS)
            logger.info("Added header row to Google Sheet.")
        return sheet

    except Exception as e:
        logger.error(f"Google Sheets connection error: {e}")
        return None


def log_application(
    job: JobListing,
    status: str,
    resume_folder: Path,
    resume_version: str,
    notes: str = "",
) -> bool:
    """
    Append one row to the Google Sheet for a job application.
    Returns True if successful.
    """
    sheet = _get_sheet()
    if sheet is None:
        logger.info(f"[No Sheet] Would log: {job.title} @ {job.company} | {status}")
        return False

    row = [
        datetime.now().strftime("%Y-%m-%d %H:%M"),
        job.title,
        job.company,
        job.location,
        job.apply_url,
        status,
        resume_version,
        str(resume_folder),
        job.source,
        notes,
    ]

    try:
        sheet.append_row(row)
        logger.info(f"Logged to Sheets: {job.title} @ {job.company} [{status}]")
        return True
    except Exception as e:
        logger.error(f"Failed to log to Google Sheets: {e}")
        return False


def update_application_status(job_url: str, new_status: str) -> bool:
    """
    Find a row by job URL and update its Status column.
    Useful for follow-up status updates (Interview, Offer, Rejected, etc.).
    """
    sheet = _get_sheet()
    if sheet is None:
        return False

    try:
        url_col = SHEET_COLUMNS.index("Job URL") + 1
        status_col = SHEET_COLUMNS.index("Status") + 1

        # Find the cell matching the URL
        cell = sheet.find(job_url, in_column=url_col)
        if cell:
            sheet.update_cell(cell.row, status_col, new_status)
            logger.info(f"Updated status to '{new_status}' for: {job_url}")
            return True
        else:
            logger.warning(f"Job URL not found in sheet: {job_url}")
            return False
    except Exception as e:
        logger.error(f"Error updating status: {e}")
        return False


def get_all_applications() -> list[dict]:
    """Return all tracked applications as a list of dicts."""
    sheet = _get_sheet()
    if sheet is None:
        return []
    try:
        records = sheet.get_all_records()
        return records
    except Exception as e:
        logger.error(f"Error reading applications: {e}")
        return []
