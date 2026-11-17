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

class ULCyberparkSource:
    name = "ulcyberpark"

    def __init__(
        self,
        base_url: str = "https://www.ulcyberpark.com",
        user_agent: str = "jobbot/0.1 (job search bot; user@example.com)",
        delay: float = 1.0,
        max_pages: int = 5
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": user_agent}
        self.delay = delay
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _parse_date(self, text: Optional[str]) -> Optional[date]:
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
        url = f"{self.base_url}/jobs"
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            jobs = self.parse_list_page(resp.text)
            return jobs
        except Exception as e:
            logger.error(f"Failed to fetch UL Cyberpark jobs list: {e}")
            return []

    def parse_list_page(self, html_content: str) -> List[Job]:
        soup = BeautifulSoup(html_content, "lxml")
        table = soup.find("table")
        if not table:
            return []

        jobs: List[Job] = []
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue

            # Column 0: Title and Closing Date
            title_el = tds[0].find("a")
            title_text = title_el.get_text(strip=True) if title_el else tds[0].get_text(strip=True)
            # Remove closing date substring from title if it was lumped in
            title_text = re.sub(r'closing date:.*', '', title_text, flags=re.I).strip()

            date_match = re.search(r'closing date:\s*([\d-]+)', tds[0].get_text(), re.I)
            deadline_str = date_match.group(1).strip() if date_match else None
            deadline_date = self._parse_date(deadline_str)

            # Column 1: Company and potential email in href
            comp_el = tds[1].find("a")
            company_name = comp_el.get_text(strip=True) if comp_el else tds[1].get_text(strip=True)
            comp_href = comp_el.get("href", "") if comp_el else ""

            # Column 2: View Details button / link
            link_el = tds[2].find("a", href=True)
            if not link_el:
                continue

            detail_url = link_el["href"]
            if not detail_url.startswith("http"):
                detail_url = f"{self.base_url}/{detail_url.lstrip('/')}"

            id_match = re.search(r'job_id=(\d+)', detail_url)
            source_job_id = id_match.group(1) if id_match else detail_url.rstrip("/").split("/")[-1]

            is_walk_in = 1 if re.search(r'walk.?in', title_text, re.I) else 0

            # Store any initial email from company href (e.g. href="http://info@tranetech.com")
            emails = []
            if "@" in comp_href:
                extracted = re.sub(r'^https?://', '', comp_href).strip('/')
                extracted = re.sub(r'^mailto:', '', extracted).strip()
                if extracted and "@" in extracted:
                    emails.append(extracted.lower())

            job = Job(
                source="ulcyberpark",
                source_job_id=str(source_job_id),
                url=detail_url,
                company=company_name,
                title=title_text,
                location_raw="Kozhikode, Kerala",
                location_class="kerala",
                posted_on=date.today(),
                deadline=deadline_date,
                is_walk_in=is_walk_in,
                emails=emails
            )
            jobs.append(job)

        return jobs

    def fetch_detail(self, job: Job) -> Job:
        try:
            resp = self.session.get(job.url, timeout=15)
            resp.raise_for_status()
            return self.parse_detail_page(job, resp.text)
        except Exception as e:
            logger.error(f"Error fetching detail for UL Cyberpark job {job.source_job_id}: {e}")
            return job

    def parse_detail_page(self, job: Job, html_content: str) -> Job:
        soup = BeautifulSoup(html_content, "lxml")
        jd_text = clean_html(html_content)
        emails = extract_emails(jd_text)

        # Merge with existing emails from list page
        for e in job.emails:
            if e not in emails:
                emails.append(e)

        # Look for mailto links
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                m_email = a["href"].replace("mailto:", "").split("?")[0].strip().lower()
                if m_email and m_email not in emails:
                    emails.append(m_email)

        # Priority sort: ensure ulcyberpark generic email is not first if company email exists
        def email_priority(e: str) -> int:
            domain = e.split("@")[-1] if "@" in e else ""
            if domain == "ulcyberpark.com":
                return 3
            user = e.split("@")[0]
            if any(p in user for p in ["hr", "careers", "jobs", "hiring", "recruitment"]):
                return 0
            if any(p in user for p in ["contact", "info", "support"]):
                return 2
            return 1

        emails.sort(key=email_priority)

        subject_override = extract_subject_override(jd_text)
        company_key = normalize_company_name(job.company)
        norm_title = normalize_title(job.title)
        jd_hash, dedupe_key = compute_hashes(company_key, norm_title, jd_text)

        if re.search(r'walk.?in', job.title, re.I) or re.search(r'walk.?in', jd_text[:500], re.I):
            job.is_walk_in = 1

        job.jd_text = jd_text
        job.emails = emails
        job.subject_override = subject_override
        job.jd_hash = jd_hash
        job.dedupe_key = dedupe_key
        return job
