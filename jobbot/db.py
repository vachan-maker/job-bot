import sqlite3
import json
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from datetime import datetime, date
from jobbot.models import Job

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  source_job_id TEXT NOT NULL,
  url TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location_raw TEXT,
  location_class TEXT,
  posted_on DATE,
  deadline DATE,
  is_walk_in INTEGER DEFAULT 0,
  emails TEXT,
  jd_text TEXT,
  jd_hash TEXT,
  dedupe_key TEXT,
  subject_override TEXT,
  role_family TEXT,
  score INTEGER,
  score_reason TEXT,
  band TEXT,
  state TEXT DEFAULT 'new',
  skip_reason TEXT,
  first_seen_at TEXT,
  last_seen_at TEXT,
  UNIQUE(source, source_job_id)
);

CREATE TABLE IF NOT EXISTS resumes (
  id INTEGER PRIMARY KEY,
  job_id INTEGER REFERENCES jobs(id),
  dir TEXT,
  tex_path TEXT,
  pdf_path TEXT,
  base_used TEXT,
  llm_model TEXT,
  validation TEXT,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY,
  job_id INTEGER UNIQUE REFERENCES jobs(id),
  to_addr TEXT,
  subject TEXT,
  message_id TEXT,
  sent_at TEXT,
  status TEXT DEFAULT 'sent',
  reply_at TEXT,
  followup_sent_at TEXT,
  resumed_from TEXT
);

CREATE TABLE IF NOT EXISTS companies (
  name_key TEXT PRIMARY KEY,
  name TEXT,
  last_contacted DATETIME,
  suppressed INTEGER DEFAULT 0,
  suppress_reason TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  at TEXT DEFAULT (datetime('now')),
  kind TEXT,
  job_id INTEGER,
  detail TEXT
);
"""

DEFAULT_DB_PATH = Path("jobbot.db")

def get_connection(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.executescript(SCHEMA)
    conn.close()

def log_event(kind: str, job_id: Optional[int] = None, detail: Optional[Dict[str, Any]] = None, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "INSERT INTO events (kind, job_id, detail) VALUES (?, ?, ?)",
            (kind, job_id, json.dumps(detail or {}))
        )
    conn.close()

def upsert_job(job: Job, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> int:
    conn = get_connection(db_path)
    now = datetime.now().isoformat()
    emails_json = json.dumps(job.emails)
    score_reason_json = json.dumps(job.score_reason) if job.score_reason else None

    with conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, first_seen_at FROM jobs WHERE source = ? AND source_job_id = ?",
            (job.source, job.source_job_id)
        )
        existing = cursor.fetchone()

        if existing:
            job_id = existing["id"]
            cursor.execute(
                """
                UPDATE jobs SET
                    url = ?, company = ?, title = ?, location_raw = ?, location_class = ?,
                    posted_on = ?, deadline = ?, is_walk_in = ?, emails = ?, jd_text = ?,
                    jd_hash = ?, dedupe_key = ?, subject_override = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    job.url, job.company, job.title, job.location_raw, job.location_class,
                    str(job.posted_on) if job.posted_on else None,
                    str(job.deadline) if job.deadline else None,
                    job.is_walk_in, emails_json, job.jd_text, job.jd_hash,
                    job.dedupe_key, job.subject_override, now, job_id
                )
            )
        else:
            cursor.execute(
                """
                INSERT INTO jobs (
                    source, source_job_id, url, company, title, location_raw, location_class,
                    posted_on, deadline, is_walk_in, emails, jd_text, jd_hash, dedupe_key,
                    subject_override, role_family, score, score_reason, band, state,
                    skip_reason, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.source, job.source_job_id, job.url, job.company, job.title, job.location_raw,
                    job.location_class, str(job.posted_on) if job.posted_on else None,
                    str(job.deadline) if job.deadline else None, job.is_walk_in, emails_json,
                    job.jd_text, job.jd_hash, job.dedupe_key, job.subject_override,
                    job.role_family, job.score, score_reason_json, job.band, job.state,
                    job.skip_reason, now, now
                )
            )
            job_id = cursor.lastrowid
    conn.close()
    return job_id

def row_to_job(row: sqlite3.Row) -> Job:
    d = dict(row)
    if d.get("emails"):
        try:
            d["emails"] = json.loads(d["emails"])
        except Exception:
            d["emails"] = []
    else:
        d["emails"] = []

    if d.get("score_reason"):
        try:
            d["score_reason"] = json.loads(d["score_reason"])
        except Exception:
            d["score_reason"] = None

    if d.get("posted_on"):
        try:
            d["posted_on"] = date.fromisoformat(str(d["posted_on"]))
        except Exception:
            d["posted_on"] = None

    if d.get("deadline"):
        try:
            d["deadline"] = date.fromisoformat(str(d["deadline"]))
        except Exception:
            d["deadline"] = None

    return Job(**d)

def get_job_by_id(job_id: int, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> Optional[Job]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row_to_job(row)
    return None

def get_jobs_by_state(state: str, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> List[Job]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE state = ? ORDER BY score DESC, id ASC", (state,))
    rows = cursor.fetchall()
    conn.close()
    return [row_to_job(r) for r in rows]

def get_jobs_by_band(band: str, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> List[Job]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE band = ? ORDER BY score DESC, id ASC", (band,))
    rows = cursor.fetchall()
    conn.close()
    return [row_to_job(r) for r in rows]

def update_job_ranking(
    job_id: int, score: int, score_reason: Dict[str, Any], band: str,
    role_family: Optional[str], state: str, skip_reason: Optional[str] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH
) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            UPDATE jobs SET
                score = ?, score_reason = ?, band = ?, role_family = ?, state = ?, skip_reason = ?
            WHERE id = ?
            """,
            (score, json.dumps(score_reason), band, role_family, state, skip_reason, job_id)
        )
    conn.close()

def update_job_state(
    job_id: int, state: str, skip_reason: Optional[str] = None,
    db_path: Union[str, Path] = DEFAULT_DB_PATH
) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            "UPDATE jobs SET state = ?, skip_reason = ? WHERE id = ?",
            (state, skip_reason, job_id)
        )
    conn.close()

def is_company_suppressed(name_key: str, cooldown_days: int = 30, db_path: Union[str, Path] = DEFAULT_DB_PATH) -> bool:
    if not name_key:
        return False
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT suppressed, last_contacted FROM companies
        WHERE name_key = ?
           OR ? LIKE (name_key || '%')
           OR name_key LIKE (? || '%')
        ORDER BY suppressed DESC LIMIT 1
        """,
        (name_key, name_key, name_key)
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return False
    if row["suppressed"]:
        return True
    if row["last_contacted"]:
        try:
            lc = datetime.fromisoformat(row["last_contacted"])
            if (datetime.now() - lc).days < cooldown_days:
                return True
        except Exception:
            pass
    return False

def suppress_company(
    name_key: str, name: Optional[str] = None, reason: str = "manual",
    db_path: Union[str, Path] = DEFAULT_DB_PATH
) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO companies (name_key, name, suppressed, suppress_reason)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(name_key) DO UPDATE SET
                suppressed = 1,
                suppress_reason = excluded.suppress_reason
            """,
            (name_key, name or name_key, reason)
        )
    conn.close()

def seed_suppressed_companies(companies_list: List[str], reason: str = "resume_seed", db_path: Union[str, Path] = DEFAULT_DB_PATH) -> None:
    for c in companies_list:
        suppress_company(c.strip().upper(), name=c.strip(), reason=reason, db_path=db_path)
