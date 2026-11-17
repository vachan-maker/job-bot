import re
import json
import time
import logging
from typing import List, Optional, Dict, Any
from datetime import date, datetime
import requests
from bs4 import BeautifulSoup

from jobbot.models import Job
from jobbot.normalize import (
    clean_html, normalize_company_name, normalize_title,
    classify_location, extract_emails, extract_subject_override, compute_hashes
)

logger = logging.getLogger(__name__)

class TechnoparkSource:
    name = "technopark"

    def __init__(
        self,
        base_url: str = "https://technopark.in",
        user_agent: str = "jobbot/0.1 (personal job search; alex.doe@example.com)",
        delay: float = 1.0,
        per_page: int = 20
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": user_agent}
        self.delay = delay
        self.per_page = per_page
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _request_with_retry(self, url: str) -> Optional[requests.Response]:
        backoff = 1.0
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=15)
                if resp.status_code in (429, 500, 502, 503, 504):
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                resp.raise_for_status()
                return resp
            except Exception as e:
                logger.warning(f"Attempt {attempt+1} failed for {url}: {e}")
                time.sleep(backoff)
                backoff *= 2
        return None

    def _parse_date(self, text: Optional[str]) -> Optional[date]:
        if not text:
            return None
        cleaned = text.strip()
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
            try:
                return datetime.strptime(cleaned[:10], fmt[:8] if "T" in fmt else fmt).date()
            except ValueError:
                pass
        return None

    def list_jobs(self, max_pages: Optional[int] = None) -> List[Job]:
        all_jobs: List[Job] = []
        page = 1
        last_page = 1

        while page <= last_page:
            if max_pages and page > max_pages:
                break

            url = f"{self.base_url}/api/paginated-jobs?page={page}"
            resp = self._request_with_retry(url)
            if not resp:
                logger.error(f"Failed to fetch Technopark API page {page}")
                break

            try:
                data = resp.json()
            except Exception as e:
                logger.error(f"Failed to parse Technopark JSON on page {page}: {e}")
                break

            # Handle paginator structure
            # Could be data.get('last_page') or data.get('data', {}).get('last_page')
            pagination = data if "last_page" in data else data.get("data", {})
            last_page = pagination.get("last_page", 1)
            raw_items = pagination.get("data", []) if "data" in pagination else data.get("data", [])

            for item in raw_items:
                job = self.parse_list_item(item)
                if job:
                    all_jobs.append(job)

            page += 1
            time.sleep(self.delay)

        return all_jobs

    def parse_list_item(self, item: Dict[str, Any]) -> Optional[Job]:
        source_job_id = str(item.get("id"))
        if not source_job_id:
            return None

        job_title = item.get("job_title", "").strip()
        company_obj = item.get("company", {})
        if isinstance(company_obj, dict):
            company_name = company_obj.get("company") or company_obj.get("name") or "Unknown"
        else:
            company_name = str(company_obj)

        posted_date = self._parse_date(item.get("posted_date"))
        closing_date = self._parse_date(item.get("closing_date"))

        is_walk_in = 1 if item.get("is_walk_in") or re.search(r'walk.?in', job_title, re.I) else 0

        # Construct detail URL
        # Usually https://technopark.in/job-details/{id}
        url = f"{self.base_url}/job-details/{source_job_id}"

        return Job(
            source="technopark",
            source_job_id=source_job_id,
            url=url,
            company=company_name,
            title=job_title,
            location_raw="Trivandrum",
            location_class="tvm",
            posted_on=posted_date,
            deadline=closing_date,
            is_walk_in=is_walk_in
        )

    def fetch_detail(self, job: Job) -> Job:
        resp = self._request_with_retry(job.url)
        if not resp:
            logger.error(f"Failed to fetch Technopark detail for job {job.source_job_id}")
            return job

        return self.parse_detail_page(job, resp.text)

    def parse_detail_page(self, job: Job, html_content: str) -> Job:
        soup = BeautifulSoup(html_content, "lxml")
        data_page_el = soup.find(attrs={"data-page": True})

        contact_email = None
        jd_html = ""
        location_raw = "Trivandrum"

        if data_page_el and data_page_el.get("data-page"):
            try:
                page_data = json.loads(data_page_el["data-page"])
                job_listing = page_data.get("props", {}).get("jobListing", {})
                contact_email = job_listing.get("contact_email")
                jd_html = job_listing.get("job_description", "")
                if job_listing.get("location"):
                    location_raw = job_listing.get("location")
            except Exception as e:
                logger.warning(f"Error parsing Inertia data-page JSON: {e}")

        if not jd_html:
            jd_html = html_content

        jd_text = clean_html(jd_html)
        emails = extract_emails(jd_text)

        if contact_email and contact_email not in emails:
            emails.insert(0, contact_email)

        # Look for mailto: links in html as well
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                m_email = a["href"].replace("mailto:", "").split("?")[0].strip()
                if m_email and m_email not in emails:
                    emails.append(m_email)

        subject_override = extract_subject_override(jd_text)
        company_key = normalize_company_name(job.company)
        norm_title = normalize_title(job.title)
        jd_hash, dedupe_key = compute_hashes(company_key, norm_title, jd_text)

        loc_class = classify_location(location_raw)

        if re.search(r'walk.?in', job.title, re.I) or re.search(r'walk.?in', jd_text[:500], re.I):
            job.is_walk_in = 1

        job.location_raw = location_raw
        job.location_class = loc_class
        job.jd_text = jd_text
        job.emails = emails
        job.subject_override = subject_override
        job.jd_hash = jd_hash
        job.dedupe_key = dedupe_key

        return job
