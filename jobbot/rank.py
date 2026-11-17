import re
import yaml
from pathlib import Path
from datetime import date, datetime
from typing import Dict, Any, Optional, Tuple, List

from jobbot.models import Job, Score
from jobbot.normalize import normalize_company_name
from jobbot.db import is_company_suppressed

def load_skills(skills_path: Path = Path("profile/skills.yaml")) -> Dict[str, Any]:
    if not skills_path.exists():
        return {}
    with open(skills_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def load_config(config_path: Path = Path("config.yaml")) -> Dict[str, Any]:
    # Check for local untracked override first
    if config_path == Path("config.yaml"):
        local_config = Path("config.local.yaml")
        if local_config.exists():
            config_path = local_config

    if not config_path.exists():
        example_path = Path("config.example.yaml")
        if example_path.exists():
            config_path = example_path
        else:
            return {}

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

def export_walk_in_ics(job: Job, out_dir: Path = Path("out/ics")) -> Optional[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r'[^a-zA-Z0-9]', '_', job.title)[:30]
    filename = out_dir / f"walkin_{job.source}_{job.source_job_id}_{slug}.ics"
    dt_str = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    event_date = (job.deadline or job.posted_on or date.today()).strftime("%Y%m%d")

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//JobBot//Walk-in Exporter//EN
BEGIN:VEVENT
UID:walkin-{job.source}-{job.source_job_id}@jobbot
DTSTAMP:{dt_str}
DTSTART;VALUE=DATE:{event_date}
SUMMARY:Walk-in: {job.title} at {job.company}
DESCRIPTION:Job URL: {job.url}\\nCompany: {job.company}\\nLocation: {job.location_raw or 'Kerala'}
LOCATION:{job.location_raw or 'Kerala'}
END:VEVENT
END:VCALENDAR"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(ics_content)
    return filename

def check_preliminary_title_filters(job: Job, config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    today = date.today()

    # 1. Expired deadline
    if job.deadline and job.deadline < today:
        return False, f"Expired deadline: {job.deadline}"

    # 2. Walk-in in title
    if job.is_walk_in == 1 or re.search(r'walk.?in', job.title, re.I):
        export_walk_in_ics(job)
        return False, "Walk-in drive (exported to .ics)"

    # 3. Seniority reject in title
    seniority_reject = [r'\bsenior\b', r'\blead\b', r'\barchitect\b', r'\bprincipal\b', r'\bmanager\b', r'\bhead\b', r'\bsr\.?\b']
    for pat in seniority_reject:
        if re.search(pat, job.title, re.I):
            return False, f"Seniority rejected: title matched '{pat}'"

    # 4. Excluded category in title
    exclude_categories = config.get("filters", {}).get("exclude_categories", [
        "sales", "marketing", "content", "accounts", "recruiter", "legal",
        "insurance", "casting", "model", "support", "bpo"
    ])
    for cat in exclude_categories:
        if re.search(rf'\b{re.escape(cat)}\b', job.title, re.I):
            return False, f"Excluded category: title matched '{cat}'"

    # 5. Location other
    if job.location_class == "other":
        return False, f"Location rejected: {job.location_raw}"

    # 6. Already applied / suppressed company
    company_key = normalize_company_name(job.company)
    cooldown = config.get("filters", {}).get("company_cooldown_days", 30)
    if is_company_suppressed(company_key, cooldown_days=cooldown):
        return False, f"Company '{job.company}' ({company_key}) is suppressed or in cooldown"

    return True, None

def check_hard_filters(job: Job, config: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    # Run preliminary title filters first
    passed, reason = check_preliminary_title_filters(job, config)
    if not passed:
        return False, reason

    # Post-detail checks:
    # 7. No contact (emails empty and no ats link)
    if not job.emails:
        ats_pattern = r'https?://[^\s]+(?:greenhouse|lever|workday|smartrecruiters|naukri|indeed|forms\.gle)[^\s]*'
        if job.jd_text and re.search(ats_pattern, job.jd_text, re.I):
            return False, "ATS application link only"
        return False, "No contact email found"

    # 8. Experience req >= 3 years extracted from JD
    if job.jd_text:
        exp_matches = re.findall(r'(\d+)\+?\s*(?:years?|yrs?)', job.jd_text, re.I)
        for exp_str in exp_matches:
            try:
                exp_val = int(exp_str)
                if exp_val >= 3:
                    return False, f"Experience requirement too high: {exp_val}+ years"
            except ValueError:
                pass

    return True, None

def classify_role_family(job: Job, skills_cfg: Dict[str, Any]) -> Tuple[Optional[str], int]:
    families = skills_cfg.get("families", {})
    title_lower = job.title.lower()
    jd_lower = (job.jd_text or "").lower()

    best_family = None
    best_score = -1

    for fam_name, fam_info in families.items():
        triggers = fam_info.get("triggers", [])
        title_hits = sum(1 for t in triggers if re.search(rf'\b{re.escape(t)}\b', title_lower))
        jd_hits = sum(1 for t in triggers if re.search(rf'\b{re.escape(t)}\b', jd_lower))
        score = (title_hits * 10) + jd_hits
        if score > best_score and score > 0:
            best_score = score
            best_family = fam_name

    return best_family, best_score

def calculate_score(job: Job, config: Dict[str, Any], skills_cfg: Dict[str, Any]) -> Score:
    components: Dict[str, int] = {}
    total = 0

    families = skills_cfg.get("families", {})
    role_family, _ = classify_role_family(job, skills_cfg)

    # 1. Must-have skill hits: 3 pts each, capped at 45
    must_have_skills: List[str] = []
    if role_family and role_family in families:
        must_have_skills = families[role_family].get("must_have", [])
    else:
        # Aggregate common skills across families
        for fam in families.values():
            must_have_skills.extend(fam.get("must_have", []))
        must_have_skills = list(set(must_have_skills))

    jd_text = (job.jd_text or "").lower()
    matched_skills = []
    for skill in must_have_skills:
        pattern = rf'\b{re.escape(skill.lower())}\b'
        if re.search(pattern, jd_text):
            matched_skills.append(skill)

    skill_pts = min(45, len(matched_skills) * 3)
    components["skills"] = skill_pts
    components["matched_skills_count"] = len(matched_skills)
    total += skill_pts

    # 2. Title / seniority fit: max 20
    # family keyword in title (+10) + fresher/junior/trainee/intern (+10)
    title_lower = job.title.lower()
    title_pts = 0
    if role_family and role_family in families:
        triggers = families[role_family].get("triggers", [])
        if any(re.search(rf'\b{re.escape(t)}\b', title_lower) for t in triggers):
            title_pts += 10
        elif any(w in title_lower for w in ["developer", "engineer", "programmer", "software"]):
            title_pts += 5

    seniority_accept = ["fresher", "junior", "trainee", "intern", "associate", "graduate", "entry", "jr", "0-1", "0-2"]
    if any(re.search(rf'\b{re.escape(s)}\b', title_lower) for s in seniority_accept):
        title_pts += 10

    components["title_seniority"] = title_pts
    total += title_pts

    # 3. Location fit: max 10
    # kochi/tvm/remote = 10; unspecified/kerala = 6; other = 0
    loc_pts = 0
    if job.location_class in ("kochi", "tvm", "remote"):
        loc_pts = 10
    elif job.location_class in ("kerala", "unspecified"):
        loc_pts = 6
    components["location"] = loc_pts
    total += loc_pts

    # 4. Recency: max 10
    # <=3 days = 10; <=7 = 7; <=14 = 3; older = 0
    recency_pts = 0
    ref_date = job.posted_on or date.today()
    age_days = (date.today() - ref_date).days
    if age_days <= 3:
        recency_pts = 10
    elif age_days <= 7:
        recency_pts = 7
    elif age_days <= 14:
        recency_pts = 3
    components["recency"] = recency_pts
    total += recency_pts

    # 5. Role family confidence: max 10
    # keyword density: hits / unique_family_keywords capped at 10
    fam_pts = 0
    if role_family and role_family in families:
        triggers = families[role_family].get("triggers", [])
        if triggers:
            hit_count = sum(1 for t in triggers if re.search(rf'\b{re.escape(t)}\b', jd_text))
            ratio = hit_count / len(triggers)
            fam_pts = min(10, int(ratio * 10))
    components["family_confidence"] = fam_pts
    total += fam_pts

    # 6. Novel company: max 5
    # company_key not in DB and not in ~/Resume/ folder names
    novel_pts = 5
    company_key = normalize_company_name(job.company)
    resume_root = Path(config.get("candidate", {}).get("resume_root", "~/Resume"))
    if resume_root.exists():
        for p in resume_root.iterdir():
            if p.is_dir() and company_key in p.name.upper():
                novel_pts = 0
                break
    components["novel_company"] = novel_pts
    total += novel_pts

    # Assign band
    band_a_thresh = config.get("ranking", {}).get("shortlist_threshold", 70)
    band_b_thresh = config.get("ranking", {}).get("review_threshold", 55)

    if total >= band_a_thresh:
        band = "A"
    elif total >= band_b_thresh:
        band = "B"
    else:
        band = "C"

    return Score(
        total=total,
        band=band,
        components=components,
        role_family=role_family
    )
