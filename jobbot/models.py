from datetime import date, datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class Job(BaseModel):
    id: Optional[int] = None
    source: str                          # "infopark" | "technopark"
    source_job_id: str
    url: str
    company: str
    title: str
    location_raw: Optional[str] = None
    location_class: Optional[str] = "unspecified" # "kochi" | "tvm" | "remote" | "other" | "unspecified"
    posted_on: Optional[date] = None
    deadline: Optional[date] = None
    is_walk_in: int = 0
    emails: List[str] = Field(default_factory=list)
    jd_text: Optional[str] = None
    jd_hash: Optional[str] = None
    dedupe_key: Optional[str] = None
    subject_override: Optional[str] = None
    role_family: Optional[str] = None
    score: Optional[int] = None
    score_reason: Optional[Dict[str, Any]] = None
    band: Optional[str] = None           # "A" | "B" | "C"
    state: str = "new"                   # new→ranked→shortlisted→tailored→drafted→approved→sent→replied|bounced|skipped|manual
    skip_reason: Optional[str] = None
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None

class Score(BaseModel):
    total: int
    band: str                            # "A" | "B" | "C"
    components: Dict[str, int]
    role_family: Optional[str] = None
    skip_reason: Optional[str] = None

class Draft(BaseModel):
    job_id: int
    to_addr: str
    subject: str
    body_text: str
    pdf_path: str
    cc: Optional[List[str]] = None
    bcc: Optional[str] = None

class SendResult(BaseModel):
    job_id: int
    message_id: str
    to_addr: str
    subject: str
    sent_at: str
    status: str = "sent"                 # "sent" | "failed" | "dry_run"
    error: Optional[str] = None
