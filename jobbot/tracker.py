import os
import imaplib
import email
from email.header import decode_header
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from jobbot.db import get_connection, suppress_company
from jobbot.normalize import normalize_company_name

load_dotenv()

def poll_imap_for_replies(db_path: Path = Path("jobbot.db")) -> Dict[str, Any]:
    gmail_user = os.getenv("GMAIL_USER") or "user@example.com"
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")

    results = {"replies_found": 0, "bounces_found": 0, "errors": []}
    if not gmail_password:
        results["errors"].append("GMAIL_APP_PASSWORD not set")
        return results

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(gmail_user, gmail_password)
        mail.select("INBOX")

        # Search for recent messages in last 30 days
        status, messages = mail.search(None, '(SINCE "01-Jan-2026")')
        if status != "OK":
            mail.logout()
            return results

        msg_ids = messages[0].split()
        conn = get_connection(db_path)
        cursor = conn.cursor()

        # Fetch all tracked message_ids
        cursor.execute("SELECT job_id, message_id, to_addr FROM applications WHERE status = 'sent'")
        tracked_apps = {row["message_id"]: row["job_id"] for row in cursor.fetchall() if row["message_id"]}

        for num in msg_ids[-100:]:  # check last 100 messages
            res, data = mail.fetch(num, "(RFC822.HEADER)")
            if res != "OK":
                continue

            raw_email = data[0][1]
            msg = email.message_from_bytes(raw_email)

            from_hdr = msg.get("From", "").lower()
            subject_hdr = msg.get("Subject", "")
            in_reply_to = msg.get("In-Reply-To", "")
            references = msg.get("References", "")

            # Check if this is a bounce
            is_bounce = False
            if "mailer-daemon" in from_hdr or "postmaster" in from_hdr or "undelivered" in subject_hdr.lower() or "mail delivery" in subject_hdr.lower():
                is_bounce = True

            matched_job_id = None
            for tracked_mid, jid in tracked_apps.items():
                if tracked_mid in in_reply_to or tracked_mid in references:
                    matched_job_id = jid
                    break

            if matched_job_id:
                now_str = datetime.now().isoformat()
                if is_bounce:
                    cursor.execute(
                        "UPDATE applications SET status = 'bounced' WHERE job_id = ?",
                        (matched_job_id,)
                    )
                    cursor.execute(
                        "UPDATE jobs SET state = 'bounced' WHERE id = ?",
                        (matched_job_id,)
                    )
                    # Suppress the company
                    cursor.execute("SELECT company FROM jobs WHERE id = ?", (matched_job_id,))
                    comp = cursor.fetchone()
                    if comp:
                        ckey = normalize_company_name(comp["company"])
                        suppress_company(ckey, comp["company"], reason="email_bounced", db_path=db_path)
                    results["bounces_found"] += 1
                else:
                    cursor.execute(
                        "UPDATE applications SET status = 'replied', reply_at = ? WHERE job_id = ?",
                        (now_str, matched_job_id)
                    )
                    cursor.execute(
                        "UPDATE jobs SET state = 'replied' WHERE id = ?",
                        (matched_job_id,)
                    )
                    results["replies_found"] += 1

        conn.commit()
        conn.close()
        mail.logout()

    except Exception as e:
        results["errors"].append(str(e))

    return results
