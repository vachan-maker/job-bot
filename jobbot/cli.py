import os
import sys
import logging
from typing import Optional, List
from pathlib import Path
from datetime import datetime, date

import typer
from rich.console import Console
from rich.table import Table

from jobbot.db import (
    init_db, upsert_job, get_connection, row_to_job,
    update_job_ranking, update_job_state, get_job_by_id,
    suppress_company, seed_suppressed_companies
)
from jobbot.models import Job, Draft
from jobbot.sources.infopark import InfoparkSource
from jobbot.sources.technopark import TechnoparkSource
from jobbot.sources.ulcyberpark import ULCyberparkSource
from jobbot.sources.smartcity import SmartCitySource
from jobbot.rank import (
    load_config, load_skills, check_hard_filters, check_preliminary_title_filters, calculate_score
)
from jobbot.tailor import tailor_job
from jobbot.mailer import render_draft, send_draft, is_within_sending_window
from jobbot.report import generate_daily_digest, generate_weekly_report
from jobbot.tracker import poll_imap_for_replies
from jobbot.normalize import normalize_company_name
from jobbot import services

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = typer.Typer(help="JobBot: Automated Job Search & Application Bot", no_args_is_help=True)
console = Console()

@app.callback()
def main_callback():
    init_db()

@app.command()
def scrape(
    source: str = typer.Option("all", "--source", "-s", help="Source to scrape: all | infopark | technopark | ulcyberpark | smartcity"),
    full: bool = typer.Option(False, "--full", "-f", help="Force re-fetch details for already seen jobs"),
    max_pages: Optional[int] = typer.Option(None, "--max-pages", "-p", help="Max pages per source")
):
    """Scrape job postings from Infopark, Technopark, UL Cyberpark, and SmartCity Kochi."""
    config = load_config()
    sources_to_run = []

    if source in ("all", "infopark"):
        cfg = config.get("sources", {}).get("infopark", {})
        if cfg.get("enabled", True):
            sources_to_run.append(
                InfoparkSource(
                    base_url=cfg.get("base_url", "https://infopark.in"),
                    user_agent=cfg.get("user_agent", "jobbot/0.1"),
                    delay=cfg.get("delay", 1.0),
                    max_pages=max_pages or cfg.get("max_pages", 30)
                )
            )

    if source in ("all", "technopark"):
        cfg = config.get("sources", {}).get("technopark", {})
        if cfg.get("enabled", True):
            sources_to_run.append(
                TechnoparkSource(
                    base_url=cfg.get("base_url", "https://technopark.in"),
                    user_agent=cfg.get("user_agent", "jobbot/0.1"),
                    delay=cfg.get("delay", 1.0),
                    per_page=cfg.get("per_page", 20)
                )
            )

    if source in ("all", "ulcyberpark"):
        cfg = config.get("sources", {}).get("ulcyberpark", {})
        if cfg.get("enabled", True):
            sources_to_run.append(
                ULCyberparkSource(
                    base_url=cfg.get("base_url", "https://www.ulcyberpark.com"),
                    user_agent=cfg.get("user_agent", "jobbot/0.1"),
                    delay=cfg.get("delay", 1.0)
                )
            )

    if source in ("all", "smartcity"):
        cfg = config.get("sources", {}).get("smartcity", {})
        if cfg.get("enabled", True):
            sources_to_run.append(
                SmartCitySource(
                    base_url=cfg.get("base_url", "https://smartcity-kochi.in"),
                    user_agent=cfg.get("user_agent", "jobbot/0.1"),
                    delay=cfg.get("delay", 1.0)
                )
            )

    total_scraped = 0
    total_details = 0

    conn = get_connection()
    cursor = conn.cursor()

    for src in sources_to_run:
        # Load already-scraped IDs for this source to enable early-stop pagination
        cursor.execute(
            "SELECT source_job_id FROM jobs WHERE source = ? AND jd_text IS NOT NULL AND jd_text != ''",
            (src.name,)
        )
        known_ids = {row["source_job_id"] for row in cursor.fetchall()}
        logger.info(f"{src.name}: {len(known_ids)} already-scraped job IDs loaded for dedup.")

        console.print(f"[bold cyan]Scraping list from {src.name}...[/bold cyan]")
        try:
            jobs = src.list_jobs(max_pages=max_pages, known_ids=known_ids if not full else None)
            console.print(f"Found [green]{len(jobs)}[/green] job listings on {src.name}.")
        except Exception as e:
            console.print(f"[bold red]Failed to scrape {src.name}: {e}[/bold red]")
            continue

        for job in jobs:
            cursor.execute("SELECT id, jd_text FROM jobs WHERE source = ? AND source_job_id = ?", (job.source, job.source_job_id))
            existing = cursor.fetchone()

            # Pre-filter by title/company before fetching detail to avoid unnecessary load
            passed_title_filter, reject_reason = check_preliminary_title_filters(job, config)

            needs_detail = full or (existing is None) or (not existing["jd_text"])
            if needs_detail and passed_title_filter:
                console.print(f"Fetching detail for [{job.source}] {job.title} at {job.company}...")
                job = src.fetch_detail(job)
                total_details += 1
            elif not passed_title_filter:
                job.state = "skipped"
                job.skip_reason = reject_reason

            upsert_job(job)
            total_scraped += 1

    conn.close()
    console.print(f"[bold green]Scrape complete![/bold green] Total processed: {total_scraped}, Details fetched: {total_details}")

@app.command()
def rank(
    min_score: int = typer.Option(55, "--min-score", "-m", help="Minimum score threshold")
):
    """Filter and score new job postings."""
    config = load_config()
    skills_cfg = load_skills()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE state = 'new' OR state IS NULL")
    rows = cursor.fetchall()

    scored_count = 0
    skipped_count = 0
    shortlisted_count = 0

    for row in rows:
        job = row_to_job(row)
        passed, reject_reason = check_hard_filters(job, config)
        if not passed:
            update_job_state(job.id, state="skipped", skip_reason=reject_reason)
            skipped_count += 1
            continue

        score_res = calculate_score(job, config, skills_cfg)
        state = "shortlisted" if score_res.band == "A" else "ranked"
        if score_res.band == "A":
            shortlisted_count += 1

        update_job_ranking(
            job_id=job.id,
            score=score_res.total,
            score_reason=score_res.components,
            band=score_res.band,
            role_family=score_res.role_family,
            state=state
        )
        scored_count += 1

    conn.close()
    console.print(
        f"[bold green]Ranking complete![/bold green] Scored: {scored_count} (Shortlisted Band A: {shortlisted_count}), Skipped: {skipped_count}"
    )

@app.command()
def review(
    band: Optional[str] = typer.Option(None, "--band", "-b", help="Filter by band: A | B | C"),
    state: Optional[str] = typer.Option(None, "--state", "-s", help="Filter by state: new|ranked|shortlisted|tailored|drafted|approved|sent|replied|bounced|skipped|manual"),
    limit: int = typer.Option(50, "--limit", "-l", help="Number of jobs to show"),
    all_jobs: bool = typer.Option(False, "--all", "-a", help="Include skipped jobs")
):
    """Review ranked jobs in a tabular view."""
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
    elif not all_jobs:
        conditions.append("state != 'skipped'")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"SELECT id, source, company, title, role_family, score, band, state, skip_reason FROM jobs {where} ORDER BY score DESC, id ASC LIMIT ?"
    params.append(limit)

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()

    band_label = f" (Band {band.upper()})" if band else ""
    state_label = f" [{state}]" if state else ""
    all_label = " [all incl. skipped]" if all_jobs else ""
    table = Table(title=f"JobBot Review Queue{band_label}{state_label}{all_label} — {len(rows)} jobs")
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Src", style="dim")
    table.add_column("Company", style="magenta")
    table.add_column("Title", style="white")
    table.add_column("Family", style="green")
    table.add_column("Score", justify="right", style="yellow")
    table.add_column("Band", justify="center", style="bold")
    table.add_column("State", style="blue")

    for r in rows:
        b = r["band"] or "-"
        band_color = {"A": "green", "B": "yellow", "C": "red"}.get(b, "dim")
        state_color = {"shortlisted": "green", "tailored": "cyan", "sent": "blue",
                       "skipped": "dim", "manual": "red", "replied": "bright_green"}.get(r["state"], "white")
        table.add_row(
            str(r["id"]),
            r["source"][:4],
            r["company"][:22],
            r["title"][:32],
            r["role_family"] or "-",
            str(r["score"] or 0),
            f"[{band_color}]{b}[/{band_color}]",
            f"[{state_color}]{r['state']}[/{state_color}]"
        )

    console.print(table)

@app.command()
def tailor(
    job_ids: List[int] = typer.Argument(None, help="Job IDs to tailor"),
    top: Optional[int] = typer.Option(None, "--top", "-t", help="Tailor top N shortlisted Band A jobs")
):
    """Tailor resume for shortlisted jobs."""
    config = load_config()
    conn = get_connection()
    cursor = conn.cursor()

    jobs_to_tailor: List[Job] = []

    if job_ids:
        for jid in job_ids:
            j = get_job_by_id(jid)
            if j:
                jobs_to_tailor.append(j)
    elif top:
        cursor.execute("SELECT * FROM jobs WHERE state = 'shortlisted' AND band = 'A' ORDER BY score DESC LIMIT ?", (top,))
        jobs_to_tailor = [row_to_job(r) for r in cursor.fetchall()]
    else:
        cursor.execute("SELECT * FROM jobs WHERE state = 'shortlisted' AND band = 'A' ORDER BY score DESC LIMIT 8")
        jobs_to_tailor = [row_to_job(r) for r in cursor.fetchall()]
    conn.close()

    if not jobs_to_tailor:
        console.print("[yellow]No eligible jobs to tailor.[/yellow]")
        return

    console.print(f"Tailoring {len(jobs_to_tailor)} resumes...")
    for job in jobs_to_tailor:
        console.print(f"Tailoring for [cyan]{job.company}[/cyan] — {job.title}...")
        res = services.tailor_single_job(job.id, config=config)
        if res["success"]:
            pdf_name = Path(res["pdf_path"]).name
            console.print(f"[bold green]Successfully tailored and validated:[/bold green] {pdf_name}")
        else:
            console.print(f"[bold red]Failed tailoring job {job.id}:[/bold red] {res.get('error') or res.get('validation')}")

@app.command()
def draft(
    job_ids: List[int] = typer.Argument(None, help="Job IDs to draft"),
    approved_only: bool = typer.Option(False, "--approved", help="Draft only approved jobs")
):
    """Draft email for tailored jobs."""
    config = load_config()
    conn = get_connection()
    cursor = conn.cursor()

    if job_ids:
        query = "SELECT * FROM jobs WHERE id IN ({})".format(','.join('?' for _ in job_ids))
        cursor.execute(query, tuple(job_ids))
    elif approved_only:
        cursor.execute("SELECT * FROM jobs WHERE state = 'approved'")
    else:
        cursor.execute("SELECT * FROM jobs WHERE state = 'tailored'")

    jobs = [row_to_job(r) for r in cursor.fetchall()]
    conn.close()

    for job in jobs:
        res = services.draft_single_job(job.id, config=config)
        if res["success"]:
            console.print(f"[green]Draft generated for Job {job.id} ({job.company}): {res['subject']}[/green]")
        else:
            console.print(f"[yellow]{res.get('error')}[/yellow]")

@app.command()
def approve(
    job_ids: List[int] = typer.Argument(None, help="Job IDs to approve"),
    all_band_a: bool = typer.Option(False, "--all-band-A", help="Approve all drafted Band A jobs")
):
    """Approve drafted applications for sending."""
    conn = get_connection()
    cursor = conn.cursor()

    if all_band_a:
        cursor.execute("SELECT id FROM jobs WHERE state = 'drafted' AND band = 'A'")
        ids = [r["id"] for r in cursor.fetchall()]
    elif job_ids:
        ids = job_ids
    else:
        console.print("[yellow]Specify job IDs or use --all-band-A[/yellow]")
        conn.close()
        return
    conn.close()

    approved_ids = services.approve_jobs_by_ids(ids)
    for jid in approved_ids:
        console.print(f"[bold green]Job {jid} approved for sending.[/bold green]")

@app.command()
def send(
    limit: int = typer.Option(6, "--limit", "-l", help="Max emails to send in this run"),
    dry_run: bool = typer.Option(False, "--dry-run", "-d", help="Render preview .eml without sending"),
    force: bool = typer.Option(False, "--force", "-f", help="Ignore the 10:00–17:00 IST sending window")
):
    """Send approved applications."""
    config = load_config()

    if not dry_run and not force:
        within_window, reason = is_within_sending_window(config)
        if not within_window:
            console.print(f"[bold yellow]Send aborted:[/bold yellow] {reason}")
            console.print("[dim]Use --force to send outside the configured window.[/dim]")
            return
    elif force and not dry_run:
        console.print("[bold yellow]⚠ --force active: bypassing sending window check.[/bold yellow]")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM jobs WHERE state = 'approved' LIMIT ?", (limit,))
    job_ids = [r["id"] for r in cursor.fetchall()]
    conn.close()

    if not job_ids:
        console.print("[yellow]No approved applications ready to send.[/yellow]")
        return

    console.print(f"Sending {len(job_ids)} applications (dry_run={dry_run})...")
    for jid in job_ids:
        res = services.send_single_job(jid, config=config, dry_run=dry_run, force=force)
        if res["success"]:
            console.print(f"[bold green]Successfully processed Job {jid}:[/bold green] {res.get('subject')} -> {res.get('to')} (Status: {res.get('status')})")
        else:
            console.print(f"[bold red]Failed processing Job {jid}:[/bold red] {res.get('error')}")

@app.command()
def followup():
    """Poll IMAP for replies and bounces."""
    console.print("[cyan]Polling IMAP for replies and bounces...[/cyan]")
    res = poll_imap_for_replies()
    console.print(f"Replies found: [green]{res['replies_found']}[/green], Bounces: [red]{res['bounces_found']}[/red]")
    if res["errors"]:
        console.print(f"[yellow]Warnings/Errors: {res['errors']}[/yellow]")

@app.command()
def status():
    """Show current pipeline summary by state and band."""
    pipeline_status = services.get_pipeline_status()

    table = Table(title="JobBot Pipeline Status")
    table.add_column("State / Metric", style="cyan")
    table.add_column("Count", justify="right", style="bold green")

    for state, cnt in pipeline_status["pipeline_states"].items():
        table.add_row(f"State: {state}", str(cnt))

    for band, cnt in pipeline_status["score_bands"].items():
        table.add_row(f"Band: {band}", str(cnt))

    apps = pipeline_status.get("applications", {})
    table.add_row("Apps Sent", str(apps.get("total_sent", 0)))
    table.add_row("Apps Replied", str(apps.get("total_replied", 0)))

    console.print(table)

@app.command()
def report(
    week: bool = typer.Option(False, "--week", "-w", help="Generate weekly performance report")
):
    """Generate and display digest or weekly report."""
    if week:
        rep = generate_weekly_report()
        console.print(rep)
    else:
        dig = generate_daily_digest()
        console.print(dig)

@app.command()
def suppress(
    target: str = typer.Argument(..., help="Company name or email to suppress"),
    reason: str = typer.Option("manual", "--reason", "-r", help="Reason for suppression")
):
    """Manually suppress a company or email."""
    res = services.suppress_company_name(target, reason=reason)
    console.print(f"[green]Suppressed '{res['company']}' ({res['name_key']}): {res['reason']}[/green]")

@app.command()
def daily():
    """Full daily workflow: scrape -> rank -> tailor top 8 -> draft -> digest."""
    console.print("[bold cyan]Starting JobBot Daily Run...[/bold cyan]")
    scrape(source="all", full=False, max_pages=None)
    rank(min_score=55)
    tailor(job_ids=None, top=8)
    draft(job_ids=None, approved_only=False)
    digest_text = generate_daily_digest()
    console.print("[bold green]Daily run completed successfully![/bold green]")
    console.print(digest_text)

@app.command()
def mcp():
    """Start JobBot as a Model Context Protocol (MCP) server over stdio."""
    from jobbot.mcp_server import run_server
    run_server()

if __name__ == "__main__":
    app()
