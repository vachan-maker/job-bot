import re
import time
import logging
from typing import List, Optional
from datetime import date, datetime
import requests
from bs4 import BeautifulSoup

from jobbot.models import Job
from jobbot.normalize import (
    clean_html, normalize_company_name, normalize_title,
    classify_location, extract_emails, extract_subject_override, compute_hashes
)

logger = logging.getLogger(__name__)

class ParseError(Exception):
    pass

class InfoparkSource:
    name = "infopark"

    def __init__(
        self,
        base_url: str = "https://infopark.in",
        user_agent: str = "jobbot/0.1 (personal job search; alex.doe@example.com)",
        delay: float = 1.0,
        max_pages: int = 30
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": user_agent}
        self.delay = delay
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _parse_date(self, text: str) -> Optional[date]:
        if not text or not text.strip():
            return None
        cleaned = text.strip()
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                pass
        return None

    def list_jobs(self, max_pages: Optional[int] = None) -> List[Job]:
        pages_to_crawl = max_pages or self.max_pages
        all_jobs: List[Job] = []
        consecutive_empty_pages = 0

        for page in range(1, pages_to_crawl + 1):
            url = f"{self.base_url}/companies-job?page={page}"
            try:
                resp = self.session.get(url, timeout=15)
                resp.raise_for_status()
            except Exception as e:
                logger.error(f"Failed to fetch Infopark page {page}: {e}")
                break

            jobs_on_page = self.parse_list_page(resp.text)
            if not jobs_on_page:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= 2:
                    if page <= 2:
                        raise ParseError(f"Infopark returned 0 job rows on 2 consecutive pages ({page-1}, {page}).")
                    break
            else:
                consecutive_empty_pages = 0
                all_jobs.extend(jobs_on_page)

            time.sleep(self.delay)

        return all_jobs

    def parse_list_page(self, html_content: str) -> List[Job]:
        soup = BeautifulSoup(html_content, "lxml")
        table = soup.find("table")
        if not table:
            return []

        rows = table.find_all("tr")
        jobs: List[Job] = []

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 4:
                continue

            posted_text = cols[0].get_text(strip=True)
            title_col = cols[1]
            title_text = title_col.get_text(strip=True)
            company_text = cols[2].get_text(strip=True)
            deadline_text = cols[3].get_text(strip=True)

            link = None
            for col in cols:
                a_tag = col.find("a", href=True)
                if a_tag and ("details" in a_tag["href"] or "company-jobs" in a_tag["href"]):
                    link = a_tag["href"]
                    break

            if not link:
                continue

            if link.startswith("/"):
                full_url = f"{self.base_url}{link}"
            elif link.startswith("http"):
                full_url = link
            else:
                full_url = f"{self.base_url}/{link}"

            match = re.search(r'/details/\d+/(\d+)', link) or re.search(r'/details/(\d+)', link)
            if match:
                source_job_id = match.group(1)
            else:
                source_job_id = link.rstrip("/").split("/")[-1]

            posted_date = self._parse_date(posted_text)
            deadline_date = self._parse_date(deadline_text)

            is_walk_in = 1 if re.search(r'walk.?in', title_text, re.I) else 0

            job = Job(
                source="infopark",
                source_job_id=str(source_job_id),
                url=full_url,
                company=company_text,
                title=title_text,
                location_raw="Kochi",
                location_class="kochi",
                posted_on=posted_date,
                deadline=deadline_date,
                is_walk_in=is_walk_in
            )
            jobs.append(job)

        return jobs

    def fetch_detail(self, job: Job) -> Job:
        try:
            resp = self.session.get(job.url, timeout=15)
            resp.raise_for_status()
            html = resp.text
            return self.parse_detail_page(job, html)
        except Exception as e:
            logger.error(f"Error fetching detail for job {job.source_job_id}: {e}")
            return job

    def parse_detail_page(self, job: Job, html_content: str) -> Job:
        soup = BeautifulSoup(html_content, "lxml")
        jd_text = clean_html(html_content)
        emails = extract_emails(jd_text)

        # Check mailto links as well
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                m_email = a["href"].replace("mailto:", "").split("?")[0].strip()
                if m_email and m_email not in emails:
                    emails.append(m_email)

        subject_override = extract_subject_override(jd_text)

        company_key = normalize_company_name(job.company)
        norm_title = normalize_title(job.title)
        jd_hash, dedupe_key = compute_hashes(company_key, norm_title, jd_text)

        # If title or JD has walk-in
        if re.search(r'walk.?in', job.title, re.I) or re.search(r'walk.?in', jd_text[:500], re.I):
            job.is_walk_in = 1

        job.jd_text = jd_text
        job.emails = emails
        job.subject_override = subject_override
        job.jd_hash = jd_hash
        job.dedupe_key = dedupe_key
        return job
