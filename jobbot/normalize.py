import re
import hashlib
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup

def clean_html(html_content: str) -> str:
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, "lxml")
    for script in soup(["script", "style", "noscript"]):
        script.extract()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)

def normalize_company_name(name: str) -> str:
    if not name:
        return ""
    # Strip legal suffixes first
    cleaned = re.sub(
        r'\s*(Pvt\.?\s*Ltd\.?|\(P\)\s*Ltd\.?|\(Pvt\)\s*Ltd\.?|LLP|LLC|Inc\.?|Private\s+Limited|Limited|Ltd\.?)\s*$',
        '',
        name.strip(),
        flags=re.I
    )
    # Strip Technologies/Technology if preceded by company name (e.g. 2Base Technologies)
    cleaned = re.sub(r'\s+(Technologies|Technology)\s*$', '', cleaned, flags=re.I)
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', ' ', cleaned)
    tokens = [t.strip().upper() for t in cleaned.split() if t.strip()]
    return "_".join(tokens)

def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r'[^a-z0-9\s]', ' ', t)
    # Strip common seniority and noise tokens for dedupe
    noise = [
        "fresher", "junior", "trainee", "intern", "associate", "graduate", "entry",
        "senior", "lead", "sr", "jr", "walk", "in", "drive", "urgent", "hiring", "immediate"
    ]
    tokens = [tok for tok in t.split() if tok and tok not in noise]
    return " ".join(tokens)

def classify_location(location_str: Optional[str]) -> str:
    if not location_str or not location_str.strip():
        return "unspecified"
    loc = location_str.lower()

    # Remote / WFH
    if any(k in loc for k in ["remote", "wfh", "work from home", "anywhere"]):
        return "remote"

    # Kochi / Cochin / Infopark
    if any(k in loc for k in ["kochi", "cochin", "infopark", "kakkanad", "ernakulam"]):
        return "kochi"

    # Trivandrum / Technopark
    if any(k in loc for k in ["trivandrum", "thiruvananthapuram", "technopark", "kazhakkoottam", "tvm"]):
        return "tvm"

    # Kerala (including Kozhikode / Calicut / Cyberpark)
    if any(k in loc for k in ["kerala", "kozhikode", "calicut", "cyberpark", "malabar", "thrissur", "kannur"]):
        return "kerala"

    # Excluded locations
    if any(k in loc for k in ["bengaluru", "bangalore", "chennai", "hyderabad", "mumbai", "pune", "delhi", "noida", "gurgaon", "gurugram", "us", "usa"]):
        return "other"

    return "unspecified"

def extract_emails(text: str) -> List[str]:
    if not text:
        return []
    pattern = r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[a-zA-Z]{2,}'
    matches = re.findall(pattern, text)
    valid_emails = []
    seen = set()

    for m in matches:
        email = m.lower().strip()
        # Filter out common false positives (e.g. image filenames mistaken for emails)
        if any(email.endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".gif", ".pdf", ".svg", ".webp"]):
            continue
        if email in seen:
            continue
        seen.add(email)
        valid_emails.append(email)

    # Sort by priority: hr@, careers@, jobs@, hiring@ first
    def email_priority(e: str) -> int:
        domain = e.split("@")[-1] if "@" in e else ""
        if domain in ["ulcyberpark.com", "technopark.in", "infopark.in"]:
            return 3
        user = e.split("@")[0]
        if any(p in user for p in ["hr", "careers", "jobs", "hiring", "recruitment", "talent"]):
            return 0
        if any(p in user for p in ["contact", "info", "support", "noreply", "no-reply"]):
            return 2
        return 1

    valid_emails.sort(key=email_priority)
    return valid_emails

def extract_subject_override(jd_text: str) -> Optional[str]:
    if not jd_text:
        return None

    # First check for quoted subject
    quoted_match = re.search(r'subject\s*(?:line)?\s*[:–-]\s*["\']([^"\']{4,100})["\']', jd_text, re.I)
    if quoted_match:
        sub = quoted_match.group(1).strip()
        if "\n" not in sub:
            return sub

    patterns = [
        r'subject\s*(?:line)?\s*[:–-]\s*["\']?([^"\n\r\.\<\>]{4,100}?)(?:["\']|\s+to\s+|\s*$|\.|\n)',
        r'email.*?with\s+subject\s*[:\s]+["\']?([^"\n\r\.\<\>]{4,100}?)(?:["\']|\s+to\s+|\s*$|\.|\n)',
        r'subject\s+should\s+be\s*[:\s]+["\']?([^"\n\r\.\<\>]{4,100}?)(?:["\']|\s+to\s+|\s*$|\.|\n)',
    ]
    for p in patterns:
        m = re.search(p, jd_text, re.I | re.M)
        if m:
            sub = m.group(1).strip()
            if 3 < len(sub) < 120 and "\n" not in sub:
                return sub
    return None

def compute_hashes(company_key: str, normalized_title: str, jd_text: Optional[str]) -> Tuple[str, str]:
    text_sample = (jd_text or "")[:2000]
    jd_hash = hashlib.sha1(text_sample.encode("utf-8")).hexdigest()
    dedupe_key = hashlib.sha1(f"{company_key}|{normalized_title}".encode("utf-8")).hexdigest()
    return jd_hash, dedupe_key
