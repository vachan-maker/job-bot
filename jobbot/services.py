"""Core service layer for JobBot.

Provides shared business logic, pipeline orchestration, and state management
used identically by both the CLI (cli.py) and MCP Server (mcp_server.py).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from jobbot.db import (
    get_connection,
    get_job_by_id,
    row_to_job,
    suppress_company as db_suppress_company,
    upsert_job
)
from jobbot.models import Job
from jobbot.normalize import normalize_company_name
from jobbot.rank import load_config, load_skills, calculate_score
from jobbot.tailor import tailor_job, clean_job_description
from jobbot.validate import get_candidate_facts_path
from jobbot.mailer import render_draft, send_draft, is_within_sending_window


def get_candidate_facts_text() -> str:
    """Fetch the candidate's confirmed resume facts and achievements."""
    path = get_candidate_facts_path()
    if path:
        return path.read_text(encoding="utf-8")
    return "No candidate facts file found (expected profile/facts.local.md or profile/facts.md)."


def get_pipeline_status() -> Dict[str, Any]:
    """Get real-time summary counts of all jobs by state and score band."""
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


def list_jobs(
    band: Optional[str] = None,
    state: Optional[str] = None,
    role_family: Optional[str] = None,
    limit: int = 25,
    include_skipped: bool = False
) -> List[Dict[str, Any]]:
    """List job postings with optional filters."""
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


def search_jobs(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Search active job postings across company name, title, and JD text."""
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


def get_job_details(job_id: int) -> Dict[str, Any]:
    """Fetch full job details by ID, including tailored resume and application if available."""
    job = get_job_by_id(job_id)
    if not job:
        return {"error": f"Job with ID {job_id} not found."}

    data = job.model_dump()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM resumes WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,))
    res_row = cursor.fetchone()
    if res_row:
        data["tailored_resume"] = dict(res_row)

    cursor.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,))
    app_row = cursor.fetchone()
    if app_row:
        data["application"] = dict(app_row)

    conn.close()
    return data


def tailor_single_job(job_id: int, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Tailor and validate a candidate resume for a single job ID.

    Updates database state to 'tailored' on success or 'manual' on failure.
    """
    job = get_job_by_id(job_id)
    if not job:
        return {"success": False, "job_id": job_id, "error": f"Job {job_id} not found."}

    config = config or load_config()
    try:
        import importlib
        import jobbot.tailor
        importlib.reload(jobbot.tailor)
        success, pdf_path, details = jobbot.tailor.tailor_job(job, config)
    except Exception:
        success, pdf_path, details = tailor_job(job, config)

    conn = get_connection()
    cursor = conn.cursor()

    if success and pdf_path:
        cursor.execute(
            """
            INSERT INTO resumes (job_id, dir, tex_path, pdf_path, base_used, validation, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job.id,
                str(pdf_path.parent),
                str(pdf_path.parent / "resume.tex"),
                str(pdf_path),
                details.get("base_used", ""),
                str(details.get("validation", {})),
                datetime.now().isoformat()
            )
        )
        cursor.execute("UPDATE jobs SET state = 'tailored', skip_reason = NULL WHERE id = ?", (job.id,))
        conn.commit()
        conn.close()
        return {
            "success": True,
            "job_id": job_id,
            "company": job.company,
            "title": job.title,
            "pdf_path": str(pdf_path),
            "base_used": details.get("base_used"),
            "validation": details.get("validation")
        }
    else:
        cursor.execute(
            "UPDATE jobs SET state = 'manual', skip_reason = 'Tailoring/Validation failed' WHERE id = ?",
            (job.id,)
        )
        conn.commit()
        conn.close()
        return {
            "success": False,
            "job_id": job_id,
            "company": job.company,
            "title": job.title,
            "error": details.get("error") or "Validation checks failed",
            "validation": details.get("validation")
        }


def manual_apply(
    company: str,
    title: str,
    raw_job_description: str,
    email: Optional[str] = None,
    url: str = "",
    config: Optional[Dict[str, Any]] = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Create, clean, tailor, and optionally send a manually entered job."""
    config = config or load_config()
    cleaned_jd = clean_job_description(raw_job_description)
    if not cleaned_jd:
        return {"success": False, "error": "Job description is empty after cleaning."}

    job = Job(
        source="manual",
        source_job_id=f"manual-{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
        url=url,
        company=company.strip(),
        title=title.strip(),
        emails=[email.strip().lower()] if email and email.strip() else [],
        jd_text=cleaned_jd,
        state="shortlisted",
    )
    score = calculate_score(job, config, load_skills())
    job.role_family = score.role_family
    job.score = score.total
    job.score_reason = score.components
    job.band = score.band
    job_id = upsert_job(job)
    job.id = job_id

    tailored = tailor_single_job(job_id, config=config)
    result = {"success": tailored.get("success", False), "job_id": job_id, "cleaned_jd": cleaned_jd}
    result.update(tailored)
    if not tailored.get("success"):
        return result

    # Keep the exact cleaned input beside the generated resume for later manual use.
    Path(tailored["pdf_path"]).parent.joinpath("job_description.txt").write_text(
        cleaned_jd, encoding="utf-8"
    )

    if not job.emails:
        result["status"] = "saved"
        result["message"] = "No recipient email supplied; tailored resume saved for manual handling."
        return result

    sent = send_single_job(job_id, config=config, force=force)
    result["email"] = sent
    result["status"] = "sent" if sent.get("success") else "saved_email_failed"
    if not sent.get("success"):
        result["message"] = "Resume was saved, but email could not be sent."
    return result
def draft_single_job(job_id: int, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generate personalized email draft for a tailored job and save .eml preview.

    Updates database state to 'drafted'.
    """
    job = get_job_by_id(job_id)
    if not job:
        return {"success": False, "job_id": job_id, "error": f"Job {job_id} not found."}

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pdf_path FROM resumes WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,))
    res_row = cursor.fetchone()
    if not res_row or not res_row["pdf_path"]:
        conn.close()
        return {"success": False, "job_id": job_id, "error": f"No tailored resume found for job {job_id}. Run tailor first."}

    pdf_path = Path(res_row["pdf_path"])
    config = config or load_config()
    draft = render_draft(job, pdf_path, config)

    # Save preview .eml
    send_draft(draft, config, dry_run=True)
    cursor.execute("UPDATE jobs SET state = 'drafted' WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()

    return {
        "success": True,
        "job_id": job_id,
        "company": job.company,
        "title": job.title,
        "to": draft.to_addr,
        "subject": draft.subject,
        "body_preview": (draft.body_text[:300] + "...") if draft.body_text else "",
        "pdf_path": str(pdf_path)
    }


def approve_jobs_by_ids(job_ids: List[int]) -> List[int]:
    """Approve a list of job IDs for sending."""
    if not job_ids:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    for jid in job_ids:
        cursor.execute("UPDATE jobs SET state = 'approved' WHERE id = ?", (jid,))
    conn.commit()
    conn.close()
    return job_ids


def approve_single_job(job_id: int) -> Dict[str, Any]:
    """Approve a single job for sending."""
    job = get_job_by_id(job_id)
    if not job:
        return {"success": False, "error": f"Job {job_id} not found."}
    approve_jobs_by_ids([job_id])
    return {"success": True, "job_id": job_id, "state": "approved"}


def send_single_job(
    job_id: int,
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    force: bool = False
) -> Dict[str, Any]:
    """Send an approved application email with resume attachment via Gmail SMTP.

    Enforces the sending window (10:00-17:00 IST) unless dry_run=True or force=True.
    """
    config = config or load_config()

    if not dry_run and not force:
        within_window, reason = is_within_sending_window(config)
        if not within_window:
            return {
                "success": False,
                "status": "window_blocked",
                "job_id": job_id,
                "error": f"Send aborted: {reason}. Use force=True to bypass."
            }

    job = get_job_by_id(job_id)
    if not job:
        return {"success": False, "job_id": job_id, "error": f"Job {job_id} not found."}

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT pdf_path, base_used FROM resumes WHERE job_id = ? ORDER BY id DESC LIMIT 1", (job_id,))
    res_row = cursor.fetchone()
    if not res_row:
        conn.close()
        return {"success": False, "job_id": job_id, "error": f"No resume found for job {job_id}. Tailor first."}

    pdf_path = Path(res_row["pdf_path"])
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
            "job_id": job_id,
            "status": res.status,
            "to": res.to_addr,
            "subject": res.subject,
            "message_id": res.message_id
        }
    else:
        conn.close()
        return {
            "success": False,
            "job_id": job_id,
            "status": "failed",
            "error": res.error
        }


def suppress_company_name(company: str, reason: str = "manual") -> Dict[str, Any]:
    """Manually suppress a company name so JobBot never applies to it."""
    ckey = normalize_company_name(company)
    db_suppress_company(ckey, name=company, reason=reason)
    return {"success": True, "company": company, "name_key": ckey, "reason": reason}
