"""
Job Fetcher Agent — Free sources, no API key required.

Sources (in priority order):
  1. LinkedIn  — public guest search (best quality, works on cloud)
  2. The Muse  — free public API, broad US tech jobs
  3. Arbeitnow — free REST API, strong remote/international listings
  4. JSearch   — optional, only if RAPIDAPI_KEY is set and healthy
"""
import time
import random
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

from config import RAPIDAPI_KEY, JOB_SEARCH_QUERIES, JOB_LOCATION, JOB_REMOTE, MAX_JOBS_PER_RUN
from utils.logger import get_logger

logger = get_logger(__name__)

# Auto-disable JSearch after a 403/401 to avoid wasting time on each query
_jsearch_disabled = False

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]

def _h() -> dict:
    return {"User-Agent": random.choice(_USER_AGENTS), "Accept-Language": "en-US,en;q=0.9"}


# ─────────────────────────────────────────────────────────────
@dataclass
class JobListing:
    job_id:          str
    title:           str
    company:         str
    location:        str
    description:     str
    apply_url:       str
    source:          str
    employment_type: str  = ""
    is_remote:       bool = False
    posted_at:       str  = ""
    salary:          str  = ""
    tags:            list[str] = field(default_factory=list)

    def short_description(self) -> str:
        return self.description[:100].split("\n")[0].strip()


# ── Source 1: LinkedIn public guest search ────────────────────
def fetch_linkedin_jobs(query: str) -> list[JobListing]:
    url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    params = {
        "keywords": query,
        "location": JOB_LOCATION,
        "f_WT":     "2" if JOB_REMOTE else "",
        "start":    "0",
        "count":    "10",
    }
    jobs: list[JobListing] = []
    try:
        resp = requests.get(url, params=params, headers=_h(), timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        for card in soup.find_all("li"):
            try:
                title_tag    = card.find("h3", class_="base-search-card__title")
                company_tag  = card.find("h4", class_="base-search-card__subtitle")
                location_tag = card.find("span", class_="job-search-card__location")
                link_tag     = card.find("a", class_="base-card__full-link")

                title     = title_tag.get_text(strip=True)    if title_tag    else ""
                company   = company_tag.get_text(strip=True)  if company_tag  else ""
                location  = location_tag.get_text(strip=True) if location_tag else JOB_LOCATION
                apply_url = link_tag["href"].split("?")[0]    if link_tag     else ""

                if not title or not apply_url:
                    continue

                urn_div = card.find("div", {"data-entity-urn": True})
                job_id  = urn_div["data-entity-urn"].split(":")[-1] if urn_div else apply_url

                jobs.append(JobListing(
                    job_id=job_id,
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
    """Grab the full description from a LinkedIn job page (best-effort)."""
    try:
        resp = requests.get(job_url, headers=_h(), timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        tag  = soup.find("div", class_="show-more-less-html__markup")
        if tag:
            return tag.get_text(separator="\n", strip=True)[:3000]
    except Exception:
        pass
    return ""


# ── Source 2: The Muse (free, no key) ────────────────────────
# Keyword → Muse category
_MUSE_CATS = {
    "qa":       "Quality Assurance",
    "test":     "Quality Assurance",
    "sdet":     "Software Engineer",
    "data":     "Data Science",
    "etl":      "Data Science",
    "azure":    "Software Engineer",
    "cloud":    "Software Engineer",
    "ai":       "Software Engineer",
    "llm":      "Software Engineer",
    "prompt":   "Data Science",
}

def fetch_muse_jobs(query: str) -> list[JobListing]:
    kw       = query.lower().split()[0]
    category = _MUSE_CATS.get(kw, "Software Engineer")
    jobs: list[JobListing] = []

    try:
        resp = requests.get(
            "https://www.themuse.com/api/public/jobs",
            params={"category": category, "page": 1, "descending": "true"},
            headers=_h(),
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])

        query_words = [w.lower() for w in query.split() if len(w) > 2]

        for item in results:
            title = item.get("name", "")
            cats  = " ".join(c.get("name","") for c in item.get("categories", []))
            text  = f"{title} {cats}".lower()

            # Include if ANY query word appears in title/category
            if not any(qw in text for qw in query_words):
                continue

            location_list = item.get("locations", [])
            location  = location_list[0].get("name", JOB_LOCATION) if location_list else JOB_LOCATION
            apply_url = item.get("refs", {}).get("landing_page", "")
            if not apply_url:
                continue

            description = BeautifulSoup(
                item.get("contents", ""), "lxml"
            ).get_text(separator="\n", strip=True)[:3000]

            jobs.append(JobListing(
                job_id=str(item.get("id", apply_url)),
                title=title,
                company=item.get("company", {}).get("name", ""),
                location=location,
                description=description or f"{title}",
                apply_url=apply_url,
                source="The Muse",
                is_remote="remote" in location.lower(),
            ))

    except requests.RequestException as e:
        logger.warning(f"The Muse failed for '{query}': {e}")

    logger.info(f"  The Muse → {len(jobs)} jobs for '{query}'")
    return jobs


# ── Source 3: Arbeitnow (free REST API, no key) ───────────────
def fetch_arbeitnow_jobs(query: str) -> list[JobListing]:
    """
    Arbeitnow offers a completely free job board API.
    Endpoint: https://www.arbeitnow.com/api/job-board-api
    Supports: ?search=keyword&page=1
    """
    jobs: list[JobListing] = []
    try:
        resp = requests.get(
            "https://www.arbeitnow.com/api/job-board-api",
            params={"search": query, "page": 1},
            headers=_h(),
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("data", [])

        for item in results:
            title     = item.get("title", "")
            apply_url = item.get("url", "")
            if not title or not apply_url:
                continue

            tags = item.get("tags", [])
            description = BeautifulSoup(
                item.get("description", ""), "lxml"
            ).get_text(separator="\n", strip=True)[:3000] or f"{title}"

            jobs.append(JobListing(
                job_id=str(item.get("slug", apply_url)),
                title=title,
                company=item.get("company_name", ""),
                location=item.get("location", "Remote") or "Remote",
                description=description,
                apply_url=apply_url,
                source="Arbeitnow",
                is_remote=item.get("remote", False),
                posted_at=item.get("created_at", ""),
                tags=tags[:5],
            ))

    except requests.RequestException as e:
        logger.warning(f"Arbeitnow failed for '{query}': {e}")

    logger.info(f"  Arbeitnow → {len(jobs)} jobs for '{query}'")
    return jobs


# ── Source 4: JSearch / RapidAPI (optional) ──────────────────
def fetch_jsearch_jobs(query: str) -> list[JobListing]:
    global _jsearch_disabled
    if _jsearch_disabled:
        return []
    if not RAPIDAPI_KEY or RAPIDAPI_KEY in ("", "your_rapidapi_key_here"):
        return []

    jobs: list[JobListing] = []
    try:
        resp = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={
                "X-RapidAPI-Key":  RAPIDAPI_KEY,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
            },
            params={
                "query":            f"{query} {JOB_LOCATION}",
                "page":             "1",
                "num_pages":        "1",
                "employment_types": "FULLTIME",
                "remote_jobs_only": "true" if JOB_REMOTE else "false",
                "date_posted":      "week",
            },
            timeout=15,
        )
        # Permanently disable on auth errors — no point retrying
        if resp.status_code in (401, 403):
            logger.warning("JSearch key invalid (403/401) — disabling for this run.")
            _jsearch_disabled = True
            return []
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
                apply_url=item.get("job_apply_link", "") or item.get("job_google_link",""),
                source=item.get("job_publisher","JSearch"),
                is_remote=item.get("job_is_remote", False),
                posted_at=item.get("job_posted_at_datetime_utc",""),
                salary=" - ".join(salary_parts),
            ))
        logger.info(f"  JSearch → {len(jobs)} jobs for '{query}'")

    except requests.RequestException as e:
        logger.warning(f"JSearch failed for '{query}': {e}")

    return jobs


# ── Main entry ────────────────────────────────────────────────
def fetch_all_jobs() -> list[JobListing]:
    """Run all queries across all sources, deduplicate, cap at MAX_JOBS_PER_RUN."""
    seen_ids: set[str] = set()
    all_jobs: list[JobListing] = []

    for query in JOB_SEARCH_QUERIES:
        if len(all_jobs) >= MAX_JOBS_PER_RUN:
            break

        logger.info(f"Searching: '{query}'")
        candidates: list[JobListing] = []

        # 1. LinkedIn — primary, best quality
        candidates += fetch_linkedin_jobs(query)
        time.sleep(random.uniform(2, 3))

        # 2. The Muse — free US tech jobs
        candidates += fetch_muse_jobs(query)
        time.sleep(random.uniform(1, 2))

        # 3. Arbeitnow — free, reliable remote/global jobs
        candidates += fetch_arbeitnow_jobs(query)
        time.sleep(random.uniform(1, 2))

        # 4. JSearch — optional, auto-disabled after first 403
        if not _jsearch_disabled:
            candidates += fetch_jsearch_jobs(query)
            time.sleep(random.uniform(2, 3))

        for job in candidates:
            uid = job.job_id or job.apply_url
            if uid in seen_ids:
                continue
            if uid:
                seen_ids.add(uid)

            # Enrich short LinkedIn descriptions
            if job.source == "LinkedIn" and len(job.description) < 200 and job.apply_url:
                job.description = _fetch_linkedin_description(job.apply_url) or job.description
                time.sleep(random.uniform(1, 2))

            all_jobs.append(job)
            if len(all_jobs) >= MAX_JOBS_PER_RUN:
                break

        # Pause between queries
        time.sleep(random.uniform(3, 5))

    logger.info(f"Total unique jobs fetched: {len(all_jobs)}")
    return all_jobs
