import os
import random
import time
import email
from email.message import EmailMessage
import smtplib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
from jinja2 import Environment, FileSystemLoader
from dotenv import load_dotenv

load_dotenv()

from jobbot.models import Job, Draft, SendResult
from jobbot.normalize import normalize_company_name

IST = ZoneInfo("Asia/Kolkata")

PITCHES = {
    "php_laravel": (
        "During my traineeship at LogicLabz and through my project Joli Aayo (a Laravel application tracker), "
        "I developed robust RESTful APIs using PHP, Laravel, Eloquent ORM, and Sanctum authentication, "
        "backed by relational MySQL schema designs."
    ),
    "qa_testing": (
        "My hands-on experience includes regression testing with Playwright on web frontends at LogicLabz, "
        "along with comprehensive API regression passes using Postman covering authentication, CRUD flows, "
        "and payload verification."
    ),
    "devops_cloud": (
        "I have solid practical foundations in Linux systems administration, Docker containerization, Dockerfiles, "
        "and volume management, certified by the University of Helsinki 'DevOps with Docker: Docker basics' program."
    ),
    "python_django": (
        "I have built backend services, database models, and CRUD endpoints using Python and Django ORM, "
        "emphasizing clean architecture, REST standards, and relational data integrity."
    ),
    "fullstack_js": (
        "I build responsive web applications using React, Node.js, and modern JavaScript, focusing on component-driven "
        "frontend design, authenticated API integration, and clean state handling."
    ),
    "ai_ml": (
        "My technical background includes practical agentic workflows and Retrieval-Augmented Generation (RAG) "
        "pipelines in Python, integrating vector search, prompt engineering, and LLM orchestration."
    )
}

def render_draft(job: Job, pdf_path: Path, config: Dict[str, Any], template_dir: Path = Path("jobbot/templates")) -> Draft:
    candidate = config.get("candidate", {})
    to_addr = job.emails[0] if job.emails else "careers@" + normalize_company_name(job.company).lower() + ".com"

    # Subject line: override if present, else standard
    if job.subject_override:
        subject = job.subject_override
    else:
        subject = f"Application: {job.title} - {candidate.get('name', 'Applicant')}"

    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("email.j2")

    fam = job.role_family or "fullstack_js"
    pitch = PITCHES.get(fam, PITCHES["fullstack_js"])

    body = template.render(
        company=job.company,
        title=job.title,
        source=job.source,
        posted_on=job.posted_on,
        pitch=pitch,
        portfolio=candidate.get("portfolio", "https://example.com"),
        candidate_name=candidate.get("name", "Applicant"),
        phone=candidate.get("phone", "+91 9876543210"),
        email=candidate.get("email", "applicant@example.com"),
        linkedin=candidate.get("linkedin", "linkedin.com/in/applicant"),
        github=candidate.get("github", "github.com/applicant")
    )

    return Draft(
        job_id=job.id or 0,
        to_addr=to_addr,
        subject=subject,
        body_text=body,
        pdf_path=str(pdf_path),
        bcc=candidate.get("email", "applicant@example.com")
    )

def is_within_sending_window(config: Dict[str, Any]) -> Tuple[bool, str]:
    now_ist = datetime.now(IST)
    sending_cfg = config.get("sending", {})

    # Weekday check (Mon=0, Sun=6)
    if sending_cfg.get("weekdays_only", True) and now_ist.weekday() >= 5:
        return False, f"Sending restricted to weekdays (today is day {now_ist.weekday()})"

    # Window check "10:00-17:00"
    window = sending_cfg.get("window", "10:00-17:00")
    try:
        start_str, end_str = window.split("-")
        start_hour, start_min = map(int, start_str.split(":"))
        end_hour, end_min = map(int, end_str.split(":"))

        current_minutes = now_ist.hour * 60 + now_ist.minute
        start_minutes = start_hour * 60 + start_min
        end_minutes = end_hour * 60 + end_min

        if not (start_minutes <= current_minutes <= end_minutes):
            return False, f"Current IST time {now_ist.strftime('%H:%M')} is outside sending window {window}"
    except Exception as e:
        return False, f"Invalid window format: {e}"

    return True, "Within window"

def create_mime_message(draft: Draft, config: Dict[str, Any]) -> EmailMessage:
    candidate = config.get("candidate", {})
    from_addr = f"{candidate.get('name', 'Applicant')} <{candidate.get('email', 'applicant@example.com')}>"

    msg = EmailMessage()
    msg["To"] = draft.to_addr
    msg["From"] = from_addr
    msg["Reply-To"] = candidate.get("email", "applicant@example.com")
    if draft.bcc:
        msg["Bcc"] = draft.bcc
    msg["Subject"] = draft.subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain="gmail.com")

    msg.set_content(draft.body_text)

    # Attach PDF
    pdf_path = Path(draft.pdf_path)
    if pdf_path.exists():
        pdf_data = pdf_path.read_bytes()
        msg.add_attachment(
            pdf_data,
            maintype="application",
            subtype="pdf",
            filename=pdf_path.name
        )

    return msg

def send_draft(
    draft: Draft,
    config: Dict[str, Any],
    dry_run: bool = False,
    preview_dir: Path = Path("out/preview")
) -> SendResult:
    msg = create_mime_message(draft, config)
    message_id = msg["Message-ID"]

    if dry_run:
        preview_dir.mkdir(parents=True, exist_ok=True)
        safe_to = draft.to_addr.replace("@", "_at_")
        eml_file = preview_dir / f"preview_{draft.job_id}_{safe_to}.eml"
        with open(eml_file, "wb") as f:
            f.write(msg.as_bytes())

        return SendResult(
            job_id=draft.job_id,
            message_id=message_id,
            to_addr=draft.to_addr,
            subject=draft.subject,
            sent_at=datetime.now().isoformat(),
            status="dry_run"
        )

    # Live sending via SMTP
    gmail_user = os.getenv("GMAIL_USER") or config.get("candidate", {}).get("email")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    if not gmail_password:
        return SendResult(
            job_id=draft.job_id,
            message_id=message_id,
            to_addr=draft.to_addr,
            subject=draft.subject,
            sent_at=datetime.now().isoformat(),
            status="failed",
            error="GMAIL_APP_PASSWORD not set in environment or .env"
        )

    recipients = [draft.to_addr]
    if draft.bcc:
        recipients.append(draft.bcc)

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
            server.starttls()
            server.login(gmail_user, gmail_password)
            server.send_message(msg, from_addr=gmail_user, to_addrs=recipients)

        return SendResult(
            job_id=draft.job_id,
            message_id=message_id,
            to_addr=draft.to_addr,
            subject=draft.subject,
            sent_at=datetime.now().isoformat(),
            status="sent"
        )
    except Exception as e:
        return SendResult(
            job_id=draft.job_id,
            message_id=message_id,
            to_addr=draft.to_addr,
            subject=draft.subject,
            sent_at=datetime.now().isoformat(),
            status="failed",
            error=str(e)
        )
