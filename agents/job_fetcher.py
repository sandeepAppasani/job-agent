"""
Job Fetcher Agent
Pulls job listings from three FREE sources — no paid API key required:

  1. LinkedIn  — public guest search (no login needed)
  2. The Muse  — free public API (no key needed)
  3. RemoteOK  — free JSON API (no key needed)

JSearch (RapidAPI) is used only when RAPIDAPI_KEY is set and valid.
"""
import time
import random
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup

from config import (
    RAPIDAPI_KEY,
    JOB_SEARCH_QUERIES,
    JOB_LOCATION,
    JOB_REMOTE,
    MAX_JOBS_PER_RUN,
)
from utils.logger import get_logger

logger = get_logger(__name__)

# Rotate user-agents to avoid simple bot blocks
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def _headers() -> dict:
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


@dataclass
class JobListing:
    job_id:          str
    title:           str
    company:         str
    location:        str
    description:     str
    apply_url:       str
    source:          str
    employment_type: str = ""
    is_remote:       bool = False
    posted_at:       str = ""
    salary:          str = ""
    tags:            list[str] = field(default_factory=list)

    def short_description(self) -> str:
        return self.description[:100].split("\n")[0].strip()


# ── Source 1: LinkedIn public guest search ────────────────────

def fetch_linkedin_jobs(query: str) -> list[JobListing]:
    """
    Scrape LinkedIn's unauthenticated job search endpoint.
    Returns up to 10 listings per query with no API key.
    """
    url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    params = {
        "keywords": query,
        "location": JOB_LOCATION,
        "f_WT": "2" if JOB_REMOTE else "",   # 2 = remote
        "start": "0",
        "count": "10",
    }
    jobs: list[JobListing] = []
    try:
        resp = requests.get(url, params=params, headers=_headers(), timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        cards = soup.find_all("li")

        for card in cards:
            try:
                job_id_tag = card.find("div", {"data-entity-urn": True})
                job_id = ""
                if job_id_tag:
                    urn = job_id_tag["data-entity-urn"]
                    job_id = urn.split(":")[-1]

                title_tag    = card.find("h3", class_="base-search-card__title")
                company_tag  = card.find("h4", class_="base-search-card__subtitle")
                location_tag = card.find("span", class_="job-search-card__location")
                link_tag     = card.find("a", class_="base-card__full-link")

                title    = title_tag.get_text(strip=True)    if title_tag    else ""
                company  = company_tag.get_text(strip=True)  if company_tag  else ""
                location = location_tag.get_text(strip=True) if location_tag else JOB_LOCATION
                apply_url = link_tag["href"].split("?")[0]   if link_tag     else ""

                if not title or not apply_url:
                    continue

                jobs.append(JobListing(
                    job_id=job_id or apply_url,
                    title=title,
                    company=company,
                    location=location,
                    description=f"{title} at {company}. {location}.",
                    apply_url=apply_url,
                    source="LinkedIn",
                    is_remote="remote" in location.lower(),
                ))
            except Exception:
                continue

    except requests.RequestException as e:
        logger.warning(f"LinkedIn fetch failed for '{query}': {e}")

    logger.info(f"  LinkedIn → {len(jobs)} jobs for '{query}'")
    return jobs


def _fetch_linkedin_description(job_url: str) -> str:
    """Fetch the full job description from a LinkedIn job page."""
    try:
        resp = requests.get(job_url, headers=_headers(), timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        desc_tag = soup.find("div", class_="show-more-less-html__markup")
        if desc_tag:
            return desc_tag.get_text(separator="\n", strip=True)[:3000]
    except Exception:
        pass
    return ""


# ── Source 2: The Muse (free public API, no key) ─────────────

_MUSE_CATEGORY_MAP = {
    "qa":          "Quality Assurance",
    "test":        "Quality Assurance",
    "sdet":        "Software Engineer",
    "data":        "Data Science",
    "etl":         "Data Science",
    "azure":       "Software Engineer",
    "cloud":       "Software Engineer",
    "ai":          "Software Engineer",
    "llm":         "Software Engineer",
    "prompt":      "Data Science",
    "engineer":    "Software Engineer",
}

def fetch_muse_jobs(query: str) -> list[JobListing]:
    """Fetch from The Muse public API — completely free, no key needed."""
    keyword = query.lower().split()[0]
    category = _MUSE_CATEGORY_MAP.get(keyword, "Software Engineer")

    url = "https://www.themuse.com/api/public/jobs"
    params = {
        "category": category,
        "level":    "Senior Level,Mid Level,Entry Level",
        "page":     1,
        "descending": "true",
    }
    jobs: list[JobListing] = []
    try:
        resp = requests.get(url, params=params, headers=_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for item in data.get("results", []):
            title = item.get("name", "")
            # Filter by query relevance
            if not any(kw.lower() in title.lower() for kw in query.split()):
                # Loose filter — include if company/category matches
                cats = [c.get("name", "") for c in item.get("categories", [])]
                if not any(query.lower() in c.lower() for c in cats):
                    continue

            company  = item.get("company", {}).get("name", "")
            location_list = item.get("locations", [])
            location = location_list[0].get("name", JOB_LOCATION) if location_list else JOB_LOCATION
            apply_url = item.get("refs", {}).get("landing_page", "")
            description = BeautifulSoup(
                item.get("contents", ""), "lxml"
            ).get_text(separator="\n", strip=True)[:3000]
            job_id = str(item.get("id", apply_url))

            if not title or not apply_url:
                continue

            jobs.append(JobListing(
                job_id=job_id,
                title=title,
                company=company,
                location=location,
                description=description or f"{title} at {company}",
                apply_url=apply_url,
                source="The Muse",
                is_remote="remote" in location.lower(),
            ))
    except requests.RequestException as e:
        logger.warning(f"The Muse fetch failed for '{query}': {e}")

    logger.info(f"  The Muse → {len(jobs)} jobs for '{query}'")
    return jobs


# ── Source 3: RemoteOK (free JSON API) ───────────────────────

_REMOTEOK_CACHE: list[dict] | None = None  # fetch once per run

def fetch_remoteok_jobs(query: str) -> list[JobListing]:
    """
    RemoteOK's free public API returns all current remote jobs.
    We fetch once per run and filter locally by query keyword.
    """
    global _REMOTEOK_CACHE

    if _REMOTEOK_CACHE is None:
        try:
            resp = requests.get(
                "https://remoteok.com/api",
                headers={**_headers(), "Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            raw = resp.json()
            # First item is a legal notice dict — skip it
            _REMOTEOK_CACHE = [r for r in raw if isinstance(r, dict) and r.get("position")]
        except Exception as e:
            logger.warning(f"RemoteOK fetch failed: {e}")
            _REMOTEOK_CACHE = []

    keywords = [w.lower() for w in query.split()]
    jobs: list[JobListing] = []

    for item in _REMOTEOK_CACHE:
        title = item.get("position", "")
        tags  = item.get("tags", [])
        combined = f"{title} {' '.join(tags)}".lower()

        if not any(kw in combined for kw in keywords):
            continue

        jobs.append(JobListing(
            job_id=str(item.get("id", item.get("url", ""))),
            title=title,
            company=item.get("company", ""),
            location="Remote",
            description=BeautifulSoup(
                item.get("description", ""), "lxml"
            ).get_text(separator="\n", strip=True)[:3000] or f"{title}",
            apply_url=item.get("url", item.get("apply_url", "")),
            source="RemoteOK",
            is_remote=True,
            posted_at=item.get("date", ""),
            tags=tags[:5],
        ))

    logger.info(f"  RemoteOK → {len(jobs)} jobs for '{query}'")
    return jobs


# ── Source 4: JSearch / RapidAPI (optional, only if key set) ─

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"

def fetch_jsearch_jobs(query: str) -> list[JobListing]:
    """Use JSearch only when a valid RapidAPI key is configured."""
    if not RAPIDAPI_KEY or RAPIDAPI_KEY in ("", "your_rapidapi_key_here"):
        return []

    headers = {
        "X-RapidAPI-Key":  RAPIDAPI_KEY,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params = {
        "query":              f"{query} {JOB_LOCATION}",
        "page":               "1",
        "num_pages":          "1",
        "employment_types":   "FULLTIME",
        "remote_jobs_only":   "true" if JOB_REMOTE else "false",
        "date_posted":        "week",
    }
    jobs: list[JobListing] = []
    try:
        resp = requests.get(JSEARCH_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        for item in resp.json().get("data", []):
            salary_parts = []
            if item.get("job_min_salary"):
                salary_parts.append(f"${item['job_min_salary']:,.0f}")
            if item.get("job_max_salary"):
                salary_parts.append(f"${item['job_max_salary']:,.0f}")
            jobs.append(JobListing(
                job_id=item.get("job_id", ""),
                title=item.get("job_title", ""),
                company=item.get("employer_name", ""),
                location=f"{item.get('job_city','')}, {item.get('job_state','')}",
                description=item.get("job_description", ""),
                apply_url=item.get("job_apply_link", "") or item.get("job_google_link", ""),
                source=item.get("job_publisher", "JSearch"),
                is_remote=item.get("job_is_remote", False),
                posted_at=item.get("job_posted_at_datetime_utc", ""),
                salary=" - ".join(salary_parts),
            ))
        logger.info(f"  JSearch → {len(jobs)} jobs for '{query}'")
    except requests.RequestException as e:
        logger.warning(f"JSearch failed for '{query}': {e}")

    return jobs


# ── Main entry point ──────────────────────────────────────────

def fetch_all_jobs() -> list[JobListing]:
    """
    Run all search queries across all available sources.
    Returns a deduplicated list capped at MAX_JOBS_PER_RUN.
    """
    seen_ids: set[str] = set()
    all_jobs: list[JobListing] = []

    # Fetch RemoteOK once (cached internally for the whole run)
    logger.info("Fetching from RemoteOK (bulk fetch)…")
    _fetch_remoteok_bulk()

    for query in JOB_SEARCH_QUERIES:
        if len(all_jobs) >= MAX_JOBS_PER_RUN:
            break

        logger.info(f"Searching: '{query}'")
        candidates: list[JobListing] = []

        # Primary: LinkedIn (best quality, real job listings)
        candidates += fetch_linkedin_jobs(query)
        time.sleep(random.uniform(2, 4))  # polite delay between sources

        # Secondary: The Muse (good US tech jobs, free)
        candidates += fetch_muse_jobs(query)
        time.sleep(random.uniform(1, 2))

        # Secondary: RemoteOK (remote-only, filtered from cache)
        candidates += fetch_remoteok_jobs(query)

        # Optional: JSearch if key configured
        if RAPIDAPI_KEY and RAPIDAPI_KEY not in ("", "your_rapidapi_key_here"):
            candidates += fetch_jsearch_jobs(query)
            time.sleep(random.uniform(2, 3))

        for job in candidates:
            uid = job.job_id or job.apply_url
            if uid in seen_ids:
                continue
            if uid:
                seen_ids.add(uid)
            # Fetch full LinkedIn description if description is too short
            if job.source == "LinkedIn" and len(job.description) < 200 and job.apply_url:
                job.description = _fetch_linkedin_description(job.apply_url) or job.description
                time.sleep(random.uniform(1, 2))

            all_jobs.append(job)
            if len(all_jobs) >= MAX_JOBS_PER_RUN:
                break

        # Delay between search queries to avoid rate limits
        time.sleep(random.uniform(3, 5))

    logger.info(f"Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs


def _fetch_remoteok_bulk():
    """Pre-warm the RemoteOK cache before query loop."""
    global _REMOTEOK_CACHE
    if _REMOTEOK_CACHE is None:
        fetch_remoteok_jobs("engineer")  # triggers the cache fill
