from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Dict, Any, List
import sqlite3

from jobbot.db import get_connection

def generate_daily_digest(db_path: Path = Path("jobbot.db"), out_dir: Path = Path("out/digests")) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT state, count(*) as cnt FROM jobs GROUP BY state")
    state_counts = {row["state"]: row["cnt"] for row in cursor.fetchall()}

    cursor.execute("SELECT band, count(*) as cnt FROM jobs GROUP BY band")
    band_counts = {row["band"]: row["cnt"] for row in cursor.fetchall()}

    cursor.execute(
        """
        SELECT id, company, title, score, band, role_family, location_raw
        FROM jobs
        WHERE band = 'A'
        ORDER BY score DESC
        LIMIT 10
        """
    )
    top_band_a = cursor.fetchall()
    conn.close()

    lines = [
        f"# JobBot Daily Digest — {today}",
        "",
        "## Summary by State",
        f"- **New / Unprocessed**: {state_counts.get('new', 0)}",
        f"- **Shortlisted**: {state_counts.get('shortlisted', 0)}",
        f"- **Tailored**: {state_counts.get('tailored', 0)}",
        f"- **Drafted**: {state_counts.get('drafted', 0)}",
        f"- **Approved**: {state_counts.get('approved', 0)}",
        f"- **Sent**: {state_counts.get('sent', 0)}",
        f"- **Replied**: {state_counts.get('replied', 0)}",
        f"- **Bounced**: {state_counts.get('bounced', 0)}",
        f"- **Skipped**: {state_counts.get('skipped', 0)}",
        f"- **Manual**: {state_counts.get('manual', 0)}",
        "",
        "## Band Breakdown",
        f"- **Band A (≥70, Shortlist)**: {band_counts.get('A', 0)}",
        f"- **Band B (55–69, Review)**: {band_counts.get('B', 0)}",
        f"- **Band C (<55, Hidden)**: {band_counts.get('C', 0)}",
        "",
        "## Top Band A Opportunities",
        "| ID | Company | Title | Family | Score | Location |",
        "|---|---|---|---|---|---|"
    ]

    for job in top_band_a:
        lines.append(
            f"| {job['id']} | {job['company']} | {job['title']} | {job['role_family'] or '-'} | {job['score']} | {job['location_raw'] or '-'} |"
        )

    digest_content = "\n".join(lines)
    digest_file = out_dir / f"digest_{today}.md"
    digest_file.write_text(digest_content, encoding="utf-8")
    return digest_content

def generate_weekly_report(db_path: Path = Path("jobbot.db")) -> str:
    conn = get_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT count(*) as cnt FROM applications")
    total_sent = cursor.fetchone()["cnt"]

    cursor.execute("SELECT count(*) as cnt FROM applications WHERE status = 'replied'")
    total_replied = cursor.fetchone()["cnt"]

    cursor.execute("SELECT count(*) as cnt FROM applications WHERE status = 'bounced'")
    total_bounced = cursor.fetchone()["cnt"]

    cursor.execute(
        """
        SELECT j.role_family, count(*) as cnt
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
        GROUP BY j.role_family
        """
    )
    family_breakdown = cursor.fetchall()
    conn.close()

    reply_rate = (total_replied / total_sent * 100) if total_sent > 0 else 0.0
    bounce_rate = (total_bounced / total_sent * 100) if total_sent > 0 else 0.0

    lines = [
        f"# JobBot Weekly Report",
        "",
        f"- **Total Sent Applications**: {total_sent}",
        f"- **Replies**: {total_replied} ({reply_rate:.1f}%)",
        f"- **Bounces**: {total_bounced} ({bounce_rate:.1f}%)",
        "",
        "## Breakdown by Role Family",
        "| Role Family | Applications Sent |",
        "|---|---|"
    ]

    for row in family_breakdown:
        fam = row["role_family"] or "other"
        lines.append(f"| {fam} | {row['cnt']} |")

    return "\n".join(lines)
