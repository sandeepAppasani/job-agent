"""
Job Search Agent — Main Orchestrator
=====================================
Runs the end-to-end automated job search workflow:

1. Monitor resume for changes
2. When triggered, fetch fresh job listings
3. Tailor resume for each job using Claude
4. Save versioned resume folder (date_title_company_snippet/)
5. Auto-apply via LinkedIn Easy Apply (if enabled)
6. Track everything in Google Sheets

Usage:
    python main.py                  # Start continuous monitor mode
    python main.py --run-once       # Run pipeline once and exit
    python main.py --update-status  # Interactive status updater
"""
import argparse
import asyncio
import sys
from pathlib import Path

from config import (
    RESUME_DIR,
    RESUME_PATH,
    APPLICATIONS_DIR,
    AUTO_APPLY_ENABLED,
    ANTHROPIC_API_KEY,
)
from agents.resume_monitor import ResumeMonitor
from agents.job_fetcher import fetch_all_jobs, JobListing
from agents.resume_tailor import tailor_resume, analyze_job_fit
from agents.job_applier import apply_to_jobs
from agents.sheets_tracker import log_application, update_application_status
from agents.drive_uploader import upload_resume
from utils.file_utils import (
    read_resume_text,
    create_application_folder,
    save_tailored_resume,
    get_resume_version,
)
from utils.logger import get_logger

logger = get_logger("main")


def validate_config():
    """Warn about missing critical configuration."""
    issues = []
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your_anthropic_api_key_here":
        issues.append("ANTHROPIC_API_KEY not set — resume tailoring will be skipped")
    if not RESUME_PATH.exists():
        issues.append(f"Resume not found at {RESUME_PATH}")

    for msg in issues:
        logger.warning(f"CONFIG: {msg}")
    return len([i for i in issues if "not found" in i]) == 0


def run_pipeline(resume_path: Path):
    """
    Full pipeline:
    1. Read current resume
    2. Fetch jobs
    3. For each job: analyze fit → tailor resume → save folder → apply → log
    """
    logger.info("=" * 60)
    logger.info("JOB SEARCH PIPELINE STARTED")
    logger.info("=" * 60)

    # --- Step 1: Read resume ---
    try:
        resume_text = read_resume_text(resume_path)
        logger.info(f"Read resume: {resume_path.name} ({len(resume_text)} chars)")
    except Exception as e:
        logger.error(f"Failed to read resume: {e}")
        return

    # --- Step 2: Fetch jobs ---
    logger.info("Fetching job listings...")
    jobs = fetch_all_jobs()
    if not jobs:
        logger.warning("No jobs found. Check your RAPIDAPI_KEY or search queries.")
        return

    logger.info(f"Processing {len(jobs)} job listings...")

    # Collect jobs that need applying for async batch
    jobs_to_apply: list[tuple[JobListing, Path]] = []

    for i, job in enumerate(jobs, 1):
        logger.info(f"\n[{i}/{len(jobs)}] {job.title} @ {job.company}")

        # --- Step 3: Analyze fit ---
        fit = analyze_job_fit(resume_text, job)
        score = fit.get("match_score", fit.get("score", 50))
        should_apply = fit.get("should_apply", True)

        logger.info(
            f"  Fit score: {score}/100 | "
            f"Matching: {fit.get('matching_skills', [])[:3]} | "
            f"Missing: {fit.get('missing_skills', [])[:3]}"
        )

        if not should_apply and score < 30:
            logger.info(f"  Skipping low-match job (score={score})")
            continue

        # --- Step 4: Tailor resume ---
        logger.info(f"  Tailoring resume...")
        tailored_text = tailor_resume(resume_text, job)

        # --- Step 5: Create application folder ---
        snippet = job.short_description()[:20]
        app_folder = create_application_folder(
            base_dir=APPLICATIONS_DIR,
            job_title=job.title,
            company=job.company,
            description_snippet=snippet,
        )

        # Save job description to folder
        (app_folder / "job_description.txt").write_text(
            f"Title: {job.title}\nCompany: {job.company}\n"
            f"Location: {job.location}\nURL: {job.apply_url}\n\n"
            f"{job.description}",
            encoding="utf-8",
        )

        # Save tailored resume
        tailored_resume_path = save_tailored_resume(
            original_resume_path=resume_path,
            tailored_text=tailored_text,
            output_folder=app_folder,
            filename_prefix="tailored_resume",
        )

        resume_version = get_resume_version(app_folder)
        jobs_to_apply.append((job, tailored_resume_path))

        # --- Step 6: Upload tailored resume to Google Drive ---
        drive_link = upload_resume(tailored_resume_path, job.title, job.company)
        if drive_link:
            logger.info(f"  Resume on Drive: {drive_link}")

        # --- Step 7: Log to Google Sheets (pre-apply) ---
        log_application(
            job=job,
            status="Tailored" if AUTO_APPLY_ENABLED else "Ready to Apply",
            resume_folder=app_folder,
            resume_version=resume_version,
            notes=f"Fit score: {score}/100 | Drive: {drive_link or 'N/A'}",
        )

    # --- Step 7: Batch auto-apply ---
    if jobs_to_apply:
        logger.info(f"\nApplying to {len(jobs_to_apply)} jobs...")
        job_list, resume_paths = zip(*jobs_to_apply)

        # Use the tailored resume for the first job as default
        # (LinkedIn will use whatever is uploaded; each folder has its own)
        apply_results = asyncio.run(
            apply_to_jobs(list(job_list), resume_paths[0])
        )

        # Update statuses in Sheets
        for job, _ in jobs_to_apply:
            status = apply_results.get(job.job_id, "Unknown")
            if status == "Applied":
                update_application_status(job.apply_url, "Applied")

    logger.info("\nPipeline completed.")
    logger.info(f"Applications saved to: {APPLICATIONS_DIR}")


def on_resume_change(resume_path: Path):
    """Callback invoked by the file monitor when the resume changes."""
    logger.info(f"Resume updated — launching pipeline for: {resume_path.name}")
    run_pipeline(resume_path)


def interactive_status_updater():
    """Simple CLI to update application statuses in the Google Sheet."""
    print("\n=== Status Updater ===")
    url = input("Enter Job URL to update: ").strip()
    if not url:
        print("No URL provided.")
        return
    statuses = ["Applied", "Interview Scheduled", "Offer", "Rejected", "Withdrawn", "Ghosted"]
    for i, s in enumerate(statuses, 1):
        print(f"  {i}. {s}")
    choice = input("Select new status (number): ").strip()
    try:
        new_status = statuses[int(choice) - 1]
        ok = update_application_status(url, new_status)
        print(f"{'Updated' if ok else 'Failed to update'} status to: {new_status}")
    except (ValueError, IndexError):
        print("Invalid choice.")


def main():
    parser = argparse.ArgumentParser(description="Automated Job Search Agent")
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run the pipeline once using the current resume and exit",
    )
    parser.add_argument(
        "--update-status",
        action="store_true",
        help="Interactive mode to update application statuses",
    )
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════╗
║         JOB SEARCH AGENT — STARTING UP          ║
╚══════════════════════════════════════════════════╝
""")

    if not validate_config():
        logger.error("Critical config error. Check your .env file.")
        sys.exit(1)

    if args.update_status:
        interactive_status_updater()
        return

    if args.run_once:
        logger.info("Running pipeline once...")
        run_pipeline(RESUME_PATH)
        return

    # Default: continuous monitor mode
    logger.info(f"Starting resume monitor on: {RESUME_DIR}")
    logger.info("The pipeline will run automatically whenever your resume is updated.")
    logger.info("Press Ctrl+C to stop.\n")

    # Run pipeline once on startup
    logger.info("Running initial pipeline scan...")
    run_pipeline(RESUME_PATH)

    # Then monitor for future changes
    monitor = ResumeMonitor(resume_dir=RESUME_DIR, on_change=on_resume_change)
    monitor.run_forever()


if __name__ == "__main__":
    main()
