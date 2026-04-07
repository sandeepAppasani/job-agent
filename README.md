# Automated Job Search Agent

End-to-end Python agent that monitors your resume, fetches job listings,
tailors your resume with Claude AI, and tracks everything in Google Sheets.

## Project Structure

```
E:\Project ClaudeAgent\
├── main.py                     ← Entry point
├── config.py                   ← All configuration
├── requirements.txt
├── .env                        ← Your secrets (copy from .env.example)
├── Resume\
│   └── Sandeep Appasani_Resume.docx   ← Your resume (monitored)
├── applications\               ← Auto-created per job application
│   └── 20250407_Data_Engineer_Google_ETL\
│       ├── tailored_resume.docx
│       ├── original_resume.docx
│       └── job_description.txt
├── agents\
│   ├── resume_monitor.py       ← Watchdog file watcher
│   ├── job_fetcher.py          ← JSearch API (LinkedIn/Indeed/Glassdoor)
│   ├── resume_tailor.py        ← Claude claude-opus-4-6 resume tailoring
│   ├── job_applier.py          ← Playwright LinkedIn Easy Apply
│   └── sheets_tracker.py      ← Google Sheets logging
├── utils\
│   ├── file_utils.py           ← Resume parsing + folder management
│   └── logger.py
├── credentials\
│   └── google_credentials.json ← (you add this — see below)
└── logs\
```

---

## Step-by-Step Setup

### 1. Install Python dependencies

```bash
cd "E:\Project ClaudeAgent"
pip install -r requirements.txt
playwright install chromium
```

### 2. Copy and fill in your `.env` file

```bash
copy .env.example .env
```

Open `.env` and fill in:

| Variable | Where to get it |
|---|---|
| `ANTHROPIC_API_KEY` | https://console.anthropic.com → API Keys |
| `RAPIDAPI_KEY` | https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch (free tier available) |
| `LINKEDIN_EMAIL` | Your LinkedIn email |
| `LINKEDIN_PASSWORD` | Your LinkedIn password |
| `GOOGLE_SHEET_NAME` | Whatever you want (created automatically) |

### 3. Set up Google Sheets API

1. Go to https://console.cloud.google.com
2. Create a project (or use existing)
3. Enable **Google Sheets API** and **Google Drive API**
4. Create a **Service Account** → generate and download JSON key
5. Save the JSON file as `E:\Project ClaudeAgent\credentials\google_credentials.json`
6. Share your target Google Sheet with the service account email (found in the JSON)

> **Note:** If you skip this step, job tracking is logged locally only.

### 4. Provide LinkedIn credentials (for auto-apply)

Add to `.env`:
```
LINKEDIN_EMAIL=you@email.com
LINKEDIN_PASSWORD=yourpassword
AUTO_APPLY_ENABLED=false   ← set to true when ready
```

> **Important:** Start with `AUTO_APPLY_ENABLED=false` to review tailored resumes first.

---

## Usage

### Option A: Monitor mode (recommended)
Watches your resume. Every time you save an updated version, the full
pipeline runs automatically.

```bash
python main.py
```

### Option B: Run once
Runs the pipeline once with the current resume and exits.

```bash
python main.py --run-once
```

### Option C: Update application status
Interactive prompt to update a status in Google Sheets
(e.g., from "Applied" → "Interview Scheduled").

```bash
python main.py --update-status
```

---

## How It Works

```
Resume updated
     │
     ▼
Read resume text (DOCX/PDF)
     │
     ▼
Fetch jobs from JSearch API
├── QA/Testing roles
├── Data Engineer roles
├── Azure roles
└── Claude/AI roles
     │
     ▼
For each job:
├── Analyze fit score (Claude)
├── Tailor resume (Claude claude-opus-4-6 + adaptive thinking)
├── Save: applications/YYYYMMDD_Title_Company_Snippet/
│   ├── tailored_resume.docx
│   ├── original_resume.docx
│   └── job_description.txt
├── Auto-apply via LinkedIn Easy Apply (if enabled)
└── Log to Google Sheets
     │
     ▼
Google Sheets row:
Date | Title | Company | Location | URL | Status | Resume Version | Folder | Source | Notes
```

---

## Google Sheets Columns

| Column | Description |
|---|---|
| Date Applied | Timestamp of application |
| Job Title | Position name |
| Company | Employer |
| Location | City/State or Remote |
| Job URL | Direct link to posting |
| Status | Tailored / Applied / Interview / Offer / Rejected |
| Resume Version | Folder name used (includes date) |
| Resume Folder | Full path to application folder |
| Job Source | LinkedIn / Indeed / Glassdoor |
| Notes | AI fit score + recommendation |

---

## Sharing LinkedIn Details

When you're ready to enable LinkedIn auto-apply, share your:
- LinkedIn email
- LinkedIn password
(Add to `.env` — never commit this file to git)

The agent uses Playwright to click "Easy Apply" buttons and upload
your tailored resume automatically.

---

## Tips

- **Review before applying**: Start with `AUTO_APPLY_ENABLED=false`, review the `applications/` folder, then enable auto-apply
- **JSearch free tier**: 200 requests/month free — sufficient for ~20 jobs per run
- **Update your resume**: Just save changes to `Resume/Sandeep Appasani_Resume.docx` — the agent detects it automatically
- **Add custom search terms**: Edit `JOB_SEARCH_QUERIES` in `config.py`
