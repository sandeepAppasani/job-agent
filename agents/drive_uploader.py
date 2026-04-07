"""
Google Drive Uploader
Uploads tailored resumes to a 'Job Applications' folder in Google Drive.
Uses the same service account credentials as the Sheets tracker.
"""
import base64
import json
import os
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import GOOGLE_CREDENTIALS_PATH
from utils.logger import get_logger

logger = get_logger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.file",
]

DRIVE_FOLDER_NAME = "Job Applications - Auto"

_drive_folder_id: str | None = None


def _load_credentials() -> Credentials | None:
    env_val = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
    if env_val:
        try:
            decoded = base64.b64decode(env_val).decode("utf-8")
            info = json.loads(decoded)
            return Credentials.from_service_account_info(info, scopes=SCOPES)
        except Exception as e:
            logger.error(f"Drive: failed to load credentials from env var: {e}")
            return None

    creds_path = Path(GOOGLE_CREDENTIALS_PATH)
    if creds_path.exists():
        try:
            return Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
        except Exception as e:
            logger.error(f"Drive: failed to load credentials from file: {e}")
            return None

    logger.warning("Drive: no credentials found — upload disabled.")
    return None


def _get_or_create_folder(service, folder_name: str) -> str | None:
    """Return the Drive folder ID, creating it if it doesn't exist."""
    query = (
        f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' "
        f"and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    folder_meta = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=folder_meta, fields="id").execute()
    logger.info(f"Drive: created folder '{folder_name}'")
    return folder.get("id")


def upload_resume(file_path: Path, job_title: str, company: str) -> str | None:
    """
    Upload a resume file to Google Drive.
    Returns the shareable Drive URL or None on failure.
    """
    global _drive_folder_id

    creds = _load_credentials()
    if creds is None:
        return None

    if not file_path.exists():
        logger.warning(f"Drive: file not found — {file_path}")
        return None

    try:
        service = build("drive", "v3", credentials=creds)

        if _drive_folder_id is None:
            _drive_folder_id = _get_or_create_folder(service, DRIVE_FOLDER_NAME)

        # Name the file clearly
        safe_title = job_title.replace("/", "-")[:40]
        safe_company = company.replace("/", "-")[:20]
        drive_filename = f"{safe_title} @ {safe_company} - tailored_resume{file_path.suffix}"

        file_meta = {
            "name": drive_filename,
            "parents": [_drive_folder_id] if _drive_folder_id else [],
        }
        media = MediaFileUpload(str(file_path), resumable=False)
        uploaded = service.files().create(
            body=file_meta,
            media_body=media,
            fields="id, webViewLink",
        ).execute()

        link = uploaded.get("webViewLink", "")
        logger.info(f"Drive: uploaded '{drive_filename}' → {link}")
        return link

    except Exception as e:
        logger.error(f"Drive upload failed: {e}")
        return None
