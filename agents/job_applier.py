"""
Job Applier Agent
Automates job applications via LinkedIn Easy Apply using Playwright.
Requires LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env
"""
import asyncio
from pathlib import Path

from config import LINKEDIN_EMAIL, LINKEDIN_PASSWORD, AUTO_APPLY_ENABLED
from agents.job_fetcher import JobListing
from utils.logger import get_logger

logger = get_logger(__name__)


class LinkedInApplier:
    """Automates LinkedIn Easy Apply for a given job listing."""

    LOGIN_URL = "https://www.linkedin.com/login"
    JOBS_URL = "https://www.linkedin.com/jobs/view/"

    def __init__(self, resume_path: Path, headless: bool = False):
        self.resume_path = resume_path
        self.headless = headless
        self._page = None
        self._browser = None
        self._playwright = None

    async def _launch(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        self._page = await context.new_page()

    async def _login(self) -> bool:
        if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
            logger.error("LinkedIn credentials not configured in .env")
            return False
        await self._page.goto(self.LOGIN_URL, wait_until="networkidle")
        await self._page.fill("#username", LINKEDIN_EMAIL)
        await self._page.fill("#password", LINKEDIN_PASSWORD)
        await self._page.click('button[type="submit"]')
        await self._page.wait_for_url("**/feed/**", timeout=15000)
        logger.info("LinkedIn login successful")
        return True

    async def apply_to_job(self, job: JobListing) -> bool:
        """
        Attempt LinkedIn Easy Apply for the given job.
        Returns True if the application was submitted.
        """
        if not AUTO_APPLY_ENABLED:
            logger.info(f"[DRY RUN] Would apply to: {job.title} @ {job.company}")
            return False

        if "linkedin.com" not in job.apply_url.lower():
            logger.info(f"Non-LinkedIn job — skipping auto-apply: {job.apply_url}")
            return False

        try:
            await self._page.goto(job.apply_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)

            # Click Easy Apply button
            easy_apply = self._page.locator('button:has-text("Easy Apply")')
            if not await easy_apply.count():
                logger.info(f"No Easy Apply button for: {job.title} @ {job.company}")
                return False

            await easy_apply.first.click()
            await asyncio.sleep(2)

            # Handle multi-step modal
            submitted = await self._fill_easy_apply_modal()
            if submitted:
                logger.info(f"Applied to: {job.title} @ {job.company}")
            return submitted

        except Exception as e:
            logger.error(f"Apply error for {job.title}: {e}")
            return False

    async def _fill_easy_apply_modal(self) -> bool:
        """Walk through Easy Apply modal steps and submit."""
        max_steps = 8
        for step in range(max_steps):
            await asyncio.sleep(1.5)

            # Upload resume if prompted
            resume_input = self._page.locator('input[type="file"]')
            if await resume_input.count():
                await resume_input.first.set_input_files(str(self.resume_path))
                await asyncio.sleep(1)

            # Check for submit button
            submit_btn = self._page.locator('button:has-text("Submit application")')
            if await submit_btn.count():
                await submit_btn.first.click()
                await asyncio.sleep(2)
                return True

            # Click Next if available
            next_btn = self._page.locator('button:has-text("Next")')
            review_btn = self._page.locator('button:has-text("Review")')

            if await next_btn.count():
                await next_btn.first.click()
            elif await review_btn.count():
                await review_btn.first.click()
            else:
                logger.warning(f"Stuck at step {step} in Easy Apply modal")
                break

        return False

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def __aenter__(self):
        await self._launch()
        await self._login()
        return self

    async def __aexit__(self, *_):
        await self.close()


async def apply_to_jobs(jobs: list[JobListing], resume_path: Path) -> dict[str, str]:
    """
    Apply to a list of jobs. Returns a dict of job_id -> application status.
    """
    results: dict[str, str] = {}

    if not AUTO_APPLY_ENABLED:
        for job in jobs:
            logger.info(f"[DRY RUN] Marked for manual apply: {job.title} @ {job.company}")
            results[job.job_id] = "Pending Manual Apply"
        return results

    async with LinkedInApplier(resume_path=resume_path, headless=True) as applier:
        for job in jobs:
            status = await applier.apply_to_job(job)
            results[job.job_id] = "Applied" if status else "Not Applied"
            await asyncio.sleep(3)  # pace requests

    return results
