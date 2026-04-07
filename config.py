"""Central configuration for the Job Search Agent."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base directory — works locally (E:\Project ClaudeAgent) and on any cloud server
BASE_DIR = Path(os.getenv("PROJECT_DIR", Path(__file__).parent))

RESUME_DIR        = BASE_DIR / os.getenv("RESUME_DIR", "Resume")
APPLICATIONS_DIR  = BASE_DIR / os.getenv("APPLICATIONS_DIR", "applications")
CREDENTIALS_DIR   = BASE_DIR / "credentials"
LOG_DIR           = BASE_DIR / "logs"

# Ensure runtime directories exist
APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
RESUME_DIR.mkdir(parents=True, exist_ok=True)

# ── API Keys ─────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY    = os.getenv("GEMINI_API_KEY", "")
RAPIDAPI_KEY      = os.getenv("RAPIDAPI_KEY", "")

# ── LinkedIn ─────────────────────────────────────────────────
LINKEDIN_EMAIL    = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

# ── Google Sheets ─────────────────────────────────────────────
GOOGLE_SHEET_NAME        = os.getenv("GOOGLE_SHEET_NAME", "Job Applications Tracker")
GOOGLE_CREDENTIALS_PATH  = BASE_DIR / os.getenv(
    "GOOGLE_CREDENTIALS_PATH", "credentials/google_credentials.json"
)

# ── Resume ────────────────────────────────────────────────────
RESUME_FILENAME = os.getenv("RESUME_FILENAME", "Sandeep Appasani_Resume.docx")
RESUME_PATH     = RESUME_DIR / RESUME_FILENAME

# ── Job Search Queries ────────────────────────────────────────
JOB_SEARCH_QUERIES = [
    # Testing roles
    "QA Engineer",
    "Test Engineer",
    "SDET Automation",
    "Quality Assurance Engineer",
    # Data Engineering roles
    "Data Engineer",
    "ETL Developer",
    # Azure roles
    "Azure Data Engineer",
    "Azure Cloud Engineer",
    # Claude / AI roles
    "AI Engineer Claude",
    "LLM Engineer",
    "Prompt Engineer",
]

JOB_LOCATION = os.getenv("JOB_LOCATION", "United States")
JOB_REMOTE   = os.getenv("JOB_REMOTE", "true").lower() == "true"

# ── Claude Model ──────────────────────────────────────────────
CLAUDE_MODEL  = "claude-opus-4-6"
GEMINI_MODEL  = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# ── Application Settings ──────────────────────────────────────
AUTO_APPLY_ENABLED = os.getenv("AUTO_APPLY_ENABLED", "false").lower() == "true"
MAX_JOBS_PER_RUN   = int(os.getenv("MAX_JOBS_PER_RUN", "20"))

# ── Google Sheets Columns ─────────────────────────────────────
SHEET_COLUMNS = [
    "Date Applied",
    "Job Title",
    "Company",
    "Location",
    "Job URL",
    "Status",
    "Resume Version",
    "Resume Folder",
    "Job Source",
    "Notes",
]
