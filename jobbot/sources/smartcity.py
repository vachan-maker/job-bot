import re
import time
import logging
from typing import List, Optional, Tuple, Set
from datetime import date, datetime
import requests
from bs4 import BeautifulSoup

from jobbot.models import Job
from jobbot.normalize import (
    clean_html, normalize_company_name, normalize_title,
    classify_location, extract_emails, extract_subject_override, compute_hashes
)

logger = logging.getLogger(__name__)

ROLE_KEYWORDS = [
    'developer', 'engineer', 'analyst', 'executive', 'lead', 'manager',
    'specialist', 'specilaist', 'designer', 'architect', 'walkin', 'walk-in',
    'qa', 'support', 'intern', 'trainee', 'programmer', 'administrator', 'admin'
]

class SmartCitySource:
    name = "smartcity"

    def __init__(
        self,
        base_url: str = "https://smartcity-kochi.in",
        user_agent: str = "jobbot/0.1 (job search bot; user@example.com)",
        delay: float = 1.0
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = {"User-Agent": user_agent}
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _parse_date(self, text: Optional[str]) -> Optional[date]:
        if not text or not text.strip():
            return None
        cleaned = text.strip()
        # SmartCity uses e.g. "03Jul 26", "27Mar 25", "05Nov 24"
        for fmt in ("%d%b %y", "%d %b %y", "%d%b %Y", "%d %B %Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(cleaned, fmt).date()
            except ValueError:
                pass
        return None

    def _parse_title_and_company(self, raw_title: str) -> Tuple[str, str]:
        t = raw_title.strip()
        company = "SmartCity Tenant"
        role = t

        if "|" in t:
            parts = [p.strip() for p in t.split("|") if p.strip()]
            clean_parts = [p for p in parts if "smartcity" not in p.lower()]
            if len(clean_parts) == 2:
                p0, p1 = clean_parts[0], clean_parts[1]
                p0_role = any(k in p0.lower() for k in ROLE_KEYWORDS)
                p1_role = any(k in p1.lower() for k in ROLE_KEYWORDS)
                if p0_role and not p1_role:
                    role, company = p0, p1
                elif p1_role and not p0_role:
                    role, company = p1, p0
                else:
                    # Default: shorter part is often company, longer is role
                    if len(p0) > len(p1):
                        role, company = p0, p1
                    else:
                        role, company = p1, p0
            elif len(clean_parts) == 1:
                role = clean_parts[0]
        elif "@" in t:
            p0, p1 = t.split("@", 1)
            role = p0.strip()
            comp = re.sub(r',?\s*smartcity.*', '', p1, flags=re.I).strip()
            company = comp or company
        elif " at " in t.lower():
            p0, p1 = re.split(r'\s+at\s+', t, maxsplit=1, flags=re.I)
            role = p0.strip()
            comp = re.sub(r',?\s*smartcity.*', '', p1, flags=re.I).strip()
            company = comp or company

        # Remove trailing/leading punctuation
        role = re.sub(r'^[|\-–—\s]+|[|\-–—\s]+$', '', role).strip()
        company = re.sub(r'^[|\-–—\s]+|[|\-–—\s]+$', '', company).strip()

        return role or t, company or "SmartCity Tenant"

    def list_jobs(self, max_pages: Optional[int] = None, known_ids: Optional[Set[str]] = None) -> List[Job]:
        url = f"{self.base_url}/media-hub/job-openings/"
        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return self.parse_list_page(resp.text)
        except Exception as e:
            logger.error(f"Failed to fetch SmartCity Kochi jobs list: {e}")
            return []

    def parse_list_page(self, html_content: str) -> List[Job]:
        soup = BeautifulSoup(html_content, "lxml")
        entries = soup.select(".vcex-recent-news-entry, [class*='category-job_openings']")
        if not entries:
            # Fallback to any article or post containing job_openings
            entries = soup.find_all("article")

        jobs: List[Job] = []
        for e in entries:
            title_el = e.find(["h2", "h3", "h4", "a"], class_=lambda c: c and "title" in c) or e.find(["h2", "h3", "h4"])
            if not title_el:
                continue

            raw_title = title_el.get_text(strip=True)
            link_el = e.find("a", href=True)
            if not link_el:
                continue

            link = link_el["href"]

            date_el = e.find(class_=lambda c: c and "date" in c) or e.find("time")
            posted_date = self._parse_date(date_el.get_text(strip=True)) if date_el else None

            # Extract source_job_id from post classes (e.g. post-8471) or URL slug
            source_job_id = None
            classes = e.get("class", [])
            for c in classes:
                m = re.match(r'post-(\d+)', c)
                if m:
                    source_job_id = m.group(1)
                    break

            if not source_job_id:
                source_job_id = link.rstrip("/").split("/")[-1]

            role_title, company_name = self._parse_title_and_company(raw_title)
            is_walk_in = 1 if re.search(r'walk.?in', raw_title, re.I) else 0

            job = Job(
                source="smartcity",
                source_job_id=str(source_job_id),
                url=link,
                company=company_name,
                title=role_title,
                location_raw="SmartCity, Kochi",
                location_class="kochi",
                posted_on=posted_date,
                deadline=None,
                is_walk_in=is_walk_in,
                emails=[]
            )
            jobs.append(job)

        return jobs

    def fetch_detail(self, job: Job) -> Job:
        try:
            resp = self.session.get(job.url, timeout=15)
            resp.raise_for_status()
            return self.parse_detail_page(job, resp.text)
        except Exception as e:
            logger.error(f"Error fetching detail for SmartCity Kochi job {job.source_job_id}: {e}")
            return job

    def parse_detail_page(self, job: Job, html_content: str) -> Job:
        soup = BeautifulSoup(html_content, "lxml")
        entry_content = soup.find(class_=lambda c: c and ("entry-content" in c or "single-post-content" in c)) or soup.find("article")
        content_html = str(entry_content) if entry_content else html_content

        jd_text = clean_html(content_html)
        emails = extract_emails(jd_text)

        # Look for mailto links
        for a in soup.find_all("a", href=True):
            if a["href"].startswith("mailto:"):
                m_email = a["href"].replace("mailto:", "").split("?")[0].strip().lower()
                if m_email and m_email not in emails:
                    emails.append(m_email)

        # Priority sort: ensure smartcity-kochi.in generic email is deprioritized
        def email_priority(e: str) -> int:
            domain = e.split("@")[-1] if "@" in e else ""
            if domain in ["smartcity-kochi.in", "ulcyberpark.com", "technopark.in", "infopark.in"]:
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
