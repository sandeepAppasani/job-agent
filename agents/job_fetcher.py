"""
Job Fetcher Agent
Searches for job listings using JSearch API (RapidAPI).
Covers: QA/Testing, Data Engineering, Azure, Claude/AI roles.
"""
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from config import RAPIDAPI_KEY, JOB_SEARCH_QUERIES, JOB_LOCATION, JOB_REMOTE, MAX_JOBS_PER_RUN
from utils.logger import get_logger

logger = get_logger(__name__)

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"
JSEARCH_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
}


@dataclass
class JobListing:
    job_id: str
    title: str
    company: str
    location: str
    description: str
    apply_url: str
    source: str
    employment_type: str = ""
    is_remote: bool = False
    posted_at: str = ""
    salary: str = ""
    tags: list[str] = field(default_factory=list)

    def short_description(self) -> str:
        """Return first 100 chars of description for folder naming."""
        return self.description[:100].split("\n")[0].strip()


def fetch_jobs_jsearch(query: str, num_pages: int = 1) -> list[JobListing]:
    """Fetch jobs from JSearch API for a given search query."""
    if not RAPIDAPI_KEY or RAPIDAPI_KEY == "your_rapidapi_key_here":
        logger.warning("RAPIDAPI_KEY not set — returning empty results for JSearch.")
        return []

    jobs: list[JobListing] = []
    employment_type = "FULLTIME"
    remote_jobs_only = "true" if JOB_REMOTE else "false"

    for page in range(1, num_pages + 1):
        params = {
            "query": f"{query} {JOB_LOCATION}",
            "page": str(page),
            "num_pages": "1",
            "employment_types": employment_type,
            "remote_jobs_only": remote_jobs_only,
            "date_posted": "week",  # only recent listings
        }
        try:
            resp = requests.get(
                JSEARCH_URL,
                headers=JSEARCH_HEADERS,
                params=params,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error(f"JSearch API error for query '{query}': {e}")
            break

        for item in data.get("data", []):
            jobs.append(_parse_jsearch_item(item))
        time.sleep(0.5)  # be polite to the API

    logger.info(f"Fetched {len(jobs)} jobs for query: '{query}'")
    return jobs


def _parse_jsearch_item(item: dict[str, Any]) -> JobListing:
    salary_parts = []
    if item.get("job_min_salary"):
        salary_parts.append(f"${item['job_min_salary']:,.0f}")
    if item.get("job_max_salary"):
        salary_parts.append(f"${item['job_max_salary']:,.0f}")
    salary = " - ".join(salary_parts) if salary_parts else ""

    highlights = item.get("job_highlights", {})
    qualifications = highlights.get("Qualifications", [])

    return JobListing(
        job_id=item.get("job_id", ""),
        title=item.get("job_title", ""),
        company=item.get("employer_name", ""),
        location=item.get("job_city", "") + ", " + item.get("job_state", ""),
        description=item.get("job_description", ""),
        apply_url=item.get("job_apply_link", "") or item.get("job_google_link", ""),
        source=item.get("job_publisher", "JSearch"),
        employment_type=item.get("job_employment_type", ""),
        is_remote=item.get("job_is_remote", False),
        posted_at=item.get("job_posted_at_datetime_utc", ""),
        salary=salary,
        tags=qualifications[:5],
    )


def fetch_all_jobs() -> list[JobListing]:
    """
    Run all configured search queries and return a deduplicated list of jobs.
    Capped at MAX_JOBS_PER_RUN total.
    """
    seen_ids: set[str] = set()
    all_jobs: list[JobListing] = []

    for query in JOB_SEARCH_QUERIES:
        if len(all_jobs) >= MAX_JOBS_PER_RUN:
            break
        jobs = fetch_jobs_jsearch(query, num_pages=1)
        for job in jobs:
            if job.job_id and job.job_id in seen_ids:
                continue
            if job.job_id:
                seen_ids.add(job.job_id)
            all_jobs.append(job)
            if len(all_jobs) >= MAX_JOBS_PER_RUN:
                break

    logger.info(f"Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs
