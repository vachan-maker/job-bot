import os
import json
from pathlib import Path
from typing import Optional, List, Dict, Any

from mcp.server.mcpserver import MCPServer
from jobbot.db import (
    get_connection, row_to_job, get_job_by_id,
    suppress_company as db_suppress_company
)
from jobbot.models import Job
from jobbot.rank import (
    load_config, load_skills, check_hard_filters, check_preliminary_title_filters, calculate_score
)
from jobbot.tailor import tailor_job
from jobbot.mailer import render_draft, send_draft
from jobbot.normalize import normalize_company_name
from jobbot.sources.infopark import InfoparkSource
from jobbot.sources.technopark import TechnoparkSource
from jobbot.sources.ulcyberpark import ULCyberparkSource
from jobbot.sources.smartcity import SmartCitySource
from jobbot.report import generate_daily_digest, generate_weekly_report

# Initialize MCP Server
server = MCPServer(
    name="jobbot",
    title="JobBot: Automated Job Search & Application MCP Server",
    description="MCP server exposing JobBot's Kerala tech jobs database, scraping, ranking, resume tailoring, and email drafting tools."
)

@server.tool(
    name="get_pipeline_status",
    description="Get real-time summary counts of all jobs by state (shortlisted, tailored, sent, skipped) and score band (A, B, C)."
)
def get_pipeline_status() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT state, count(*) as cnt FROM jobs GROUP BY state")
    states = {row["state"] or "unknown": row["cnt"] for row in cursor.fetchall()}

    cursor.execute("SELECT band, count(*) as cnt FROM jobs WHERE state != 'skipped' GROUP BY band")
    bands = {row["band"] or "unranked": row["cnt"] for row in cursor.fetchall()}

    cursor.execute("SELECT count(*) as cnt FROM applications WHERE status = 'sent'")
    sent_count = cursor.fetchone()["cnt"]

    cursor.execute("SELECT count(*) as cnt FROM applications WHERE status = 'replied'")
    replied_count = cursor.fetchone()["cnt"]

    conn.close()
    return {
        "pipeline_states": states,
        "score_bands": bands,
        "applications": {
            "total_sent": sent_count,
            "total_replied": replied_count
        }
    }

@server.tool(
    name="list_jobs",
    description="List job postings with optional filters by score band ('A', 'B', 'C'), state ('shortlisted', 'ranked', 'sent', etc.), role family, or limit."
)
def list_jobs(
    band: Optional[str] = None,
    state: Optional[str] = None,
    role_family: Optional[str] = None,
    limit: int = 25,
    include_skipped: bool = False
) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()

    conditions = []
    params = []

    if band:
        conditions.append("band = ?")
        params.append(band.upper())

    if state:
        conditions.append("state = ?")
        params.append(state.lower())
    elif not include_skipped:
        conditions.append("state != 'skipped'")

    if role_family:
        conditions.append("role_family = ?")
        params.append(role_family.lower())

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT id, source, company, title, role_family, score, band, state, location_raw, emails
        FROM jobs
        {where}
        ORDER BY score DESC, id ASC
        LIMIT ?
    """
    params.append(limit)

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        if d.get("emails"):
            try:
                d["emails"] = json.loads(d["emails"])
            except Exception:
                d["emails"] = []
        results.append(d)

    return results

@server.tool(
    name="get_job_details",
    description="Fetch full details for a specific job by ID, including complete job description text, contact emails, deadline, and score breakdown."
)
def get_job_details(job_id: int) -> Dict[str, Any]:
    job = get_job_by_id(job_id)
    if not job:
        return {"error": f"Job with ID {job_id} not found."}

    data = job.model_dump()

    # Also check if a tailored resume exists
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resumes WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,))
    res_row = cursor.fetchone()
    if res_row:
        data["tailored_resume"] = dict(res_row)

    # Check application status
    cursor.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,))
    app_row = cursor.fetchone()
    if app_row:
        data["application"] = dict(app_row)

    conn.close()
    return data

@server.tool(
    name="search_jobs",
    description="Search active job postings by keyword across company name, job title, and job description."
)
def search_jobs(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    search_param = f"%{query}%"
    cursor.execute(
        """
        SELECT id, source, company, title, role_family, score, band, state, location_raw, emails
        FROM jobs
        WHERE (title LIKE ? OR company LIKE ? OR jd_text LIKE ?)
          AND state != 'skipped'
        ORDER BY score DESC, id ASC
        LIMIT ?
        """,
        (search_param, search_param, search_param, limit)
    )
    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        d = dict(r)
        if d.get("emails"):
            try:
                d["emails"] = json.loads(d["emails"])
            except Exception:
                d["emails"] = []
        results.append(d)
    return results

@server.tool(
    name="tailor_resume",
    description="Tailor and validate a candidate resume for a specific job ID. Executes base template selection, Tectonic compilation, and 6-gate validation."
)
def tailor_resume(job_id: int) -> Dict[str, Any]:
    job = get_job_by_id(job_id)
    if not job:
        return {"success": False, "error": f"Job {job_id} not found."}

    config = load_config()
    success, pdf_path, details = tailor_job(job, config)

    conn = get_connection()
    cursor = conn.cursor()
    if success and pdf_path:
        cursor.execute(
            """
            INSERT INTO resumes (job_id, dir, tex_path, pdf_path, base_used, validation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                job.id,
                str(pdf_path.parent),
                str(pdf_path.parent / "resume.tex"),
                str(pdf_path),
                details.get("base_used", ""),
                str(details.get("validation", {}))
            )
        )
        cursor.execute("UPDATE jobs SET state = 'tailored', skip_reason = NULL WHERE id = ?", (job.id,))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "job_id": job_id,
            "pdf_path": str(pdf_path),
            "base_used": details.get("base_used"),
            "validation": details.get("validation")
        }
    else:
        cursor.execute("UPDATE jobs SET state = 'manual', skip_reason = 'Tailoring failed' WHERE id = ?", (job.id,))
        conn.commit()
        conn.close()
        return {
            "success": False,
            "job_id": job_id,
            "error": details.get("error") or "Validation checks failed",
            "validation": details.get("validation")
        }

@server.tool(
    name="draft_application",
    description="Generate personalized email draft for a tailored job and save .eml preview."
)
def draft_application(job_id: int) -> Dict[str, Any]:
    job = get_job_by_id(job_id)
    if not job:
        return {"success": False, "error": f"Job {job_id} not found."}

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pdf_path FROM resumes WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,))
    res_row = cursor.fetchone()
    if not res_row or not res_row["pdf_path"]:
        conn.close()
        return {"success": False, "error": f"No tailored resume found for job {job_id}. Run tailor_resume first."}

    pdf_path = Path(res_row["pdf_path"])
    config = load_config()
    draft = render_draft(job, pdf_path, config)

    # Save preview .eml
    preview_res = send_draft(draft, config, dry_run=True)
    cursor.execute("UPDATE jobs SET state = 'drafted' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "job_id": job_id,
        "to": draft.to_addr,
        "subject": draft.subject,
        "body_preview": draft.body_text[:300] + "...",
        "pdf_path": str(pdf_path)
    }

@server.tool(
    name="approve_application",
    description="Approve a drafted application so it is queued for sending."
)
def approve_application(job_id: int) -> Dict[str, Any]:
    job = get_job_by_id(job_id)
    if not job:
        return {"success": False, "error": f"Job {job_id} not found."}

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE jobs SET state = 'approved' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return {"success": True, "job_id": job_id, "state": "approved"}

@server.tool(
    name="send_application",
    description="Send an approved application email with resume attachment via Gmail SMTP. Pass dry_run=True to preview without emailing, and force=True to bypass 10:00-17:00 IST window."
)
def send_application(job_id: int, dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
    job = get_job_by_id(job_id)
    if not job:
        return {"success": False, "error": f"Job {job_id} not found."}

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pdf_path, base_used FROM resumes WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,))
    res_row = cursor.fetchone()
    if not res_row:
        conn.close()
        return {"success": False, "error": "No resume found. Tailor the application first."}

    pdf_path = Path(res_row["pdf_path"])
    config = load_config()
    draft = render_draft(job, pdf_path, config)
    res = send_draft(draft, config, dry_run=dry_run)

    if res.status in ("sent", "dry_run"):
        cursor.execute(
            """
            INSERT OR REPLACE INTO applications (job_id, to_addr, subject, message_id, sent_at, status, resumed_from)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (job.id, res.to_addr, res.subject, res.message_id, res.sent_at, res.status, res_row["base_used"])
        )
        company_key = normalize_company_name(job.company)
        cursor.execute(
            """
            INSERT INTO companies (name_key, name, last_contacted)
            VALUES (?, ?, ?)
            ON CONFLICT(name_key) DO UPDATE SET last_contacted = excluded.last_contacted
            """,
            (company_key, job.company, res.sent_at)
        )
        new_state = "sent" if not dry_run else "approved"
        cursor.execute("UPDATE jobs SET state = ? WHERE id = ?", (new_state, job.id))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "status": res.status,
            "to": res.to_addr,
            "subject": res.subject,
            "message_id": res.message_id
        }
    else:
        conn.close()
        return {
            "success": False,
            "status": "failed",
            "error": res.error
        }

@server.tool(
    name="suppress_company",
    description="Manually suppress a company name so JobBot never applies to it."
)
def suppress_company(company: str, reason: str = "manual") -> Dict[str, Any]:
    ckey = normalize_company_name(company)
    db_suppress_company(ckey, name=company, reason=reason)
    return {"success": True, "company": company, "name_key": ckey, "reason": reason}

@server.tool(
    name="get_candidate_facts",
    description="Fetch the candidate's confirmed resume facts and achievements (source of truth)."
)
def get_candidate_facts() -> str:
    facts_path = Path("profile/facts.md")
    if facts_path.exists():
        return facts_path.read_text(encoding="utf-8")
    return "profile/facts.md not found."

@server.resource("jobbot://status", name="pipeline_status", description="Current pipeline metrics and application state counts")
def resource_pipeline_status() -> str:
    return json.dumps(get_pipeline_status(), indent=2)

@server.resource("jobbot://jobs/band-a", name="band_a_shortlist", description="Current Band A shortlisted job opportunities")
def resource_band_a() -> str:
    jobs = list_jobs(band="A")
    return json.dumps(jobs, indent=2)

@server.resource("jobbot://facts", name="candidate_facts", description="Candidate verified background, skills, and projects")
def resource_candidate_facts() -> str:
    return get_candidate_facts()

@server.prompt(
    name="review_and_tailor",
    description="Review top Band A shortlisted jobs and provide recommendations on which ones to tailor."
)
def prompt_review_and_tailor() -> str:
    return """You are JobBot's executive recruiter assistant.
1. Review the current Band A shortlisted jobs (using `list_jobs(band='A')`).
2. Read the candidate facts (`get_candidate_facts()`).
3. For each opportunity, evaluate fit against confirmed background.
4. Recommend which job to tailor next and call `tailor_resume(job_id)` on confirmed matches."""

def run_server():
    server.run(transport="stdio")

if __name__ == "__main__":
    run_server()
