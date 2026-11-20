import json
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

from mcp.server.mcpserver import MCPServer
from jobbot import services

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
    return services.get_pipeline_status()


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
    return services.list_jobs(
        band=band,
        state=state,
        role_family=role_family,
        limit=limit,
        include_skipped=include_skipped
    )


@server.tool(
    name="get_job_details",
    description="Fetch full details for a specific job by ID, including complete job description text, contact emails, deadline, and score breakdown."
)
def get_job_details(job_id: int) -> Dict[str, Any]:
    return services.get_job_details(job_id)


@server.tool(
    name="search_jobs",
    description="Search active job postings by keyword across company name, job title, and job description."
)
def search_jobs(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    return services.search_jobs(query=query, limit=limit)


@server.tool(
    name="tailor_resume",
    description="Tailor and validate a candidate resume for a specific job ID. Executes base template selection, Tectonic compilation, and 6-gate validation."
)
def tailor_resume(job_id: int) -> Dict[str, Any]:
    return services.tailor_single_job(job_id)


@server.tool(
    name="manual_apply",
    description=(
        "Create an application from a manually supplied job description. The description is cleaned and "
        "structured with an LLM before resume tailoring. If email is supplied, send the tailored resume "
        "automatically; otherwise save the resume and cleaned job description for manual handling."
    )
)
def manual_apply(
    company: str,
    title: str,
    job_description: str,
    email: Optional[str] = None,
    url: str = "",
    force: bool = False,
) -> Dict[str, Any]:
    return services.manual_apply(
        company=company,
        title=title,
        raw_job_description=job_description,
        email=email,
        url=url,
        force=force,
    )


@server.tool(
    name="draft_application",
    description="Generate personalized email draft for a tailored job and save .eml preview."
)
def draft_application(job_id: int) -> Dict[str, Any]:
    return services.draft_single_job(job_id)


@server.tool(
    name="approve_application",
    description="Approve a drafted application so it is queued for sending."
)
def approve_application(job_id: int) -> Dict[str, Any]:
    return services.approve_single_job(job_id)


@server.tool(
    name="send_application",
    description="Send an approved application email with resume attachment via Gmail SMTP. Pass dry_run=True to preview without emailing, and force=True to bypass 10:00-17:00 IST window."
)
def send_application(job_id: int, dry_run: bool = False, force: bool = False) -> Dict[str, Any]:
    return services.send_single_job(job_id, dry_run=dry_run, force=force)


@server.tool(
    name="suppress_company",
    description="Manually suppress a company name so JobBot never applies to it."
)
def suppress_company(company: str, reason: str = "manual") -> Dict[str, Any]:
    return services.suppress_company_name(company=company, reason=reason)


@server.tool(
    name="get_candidate_facts",
    description="Fetch the candidate's confirmed resume facts and achievements (source of truth)."
)
def get_candidate_facts() -> str:
    return services.get_candidate_facts_text()


@server.resource("jobbot://status", name="pipeline_status", description="Current pipeline metrics and application state counts")
def resource_pipeline_status() -> str:
    return json.dumps(services.get_pipeline_status(), indent=2)


@server.resource("jobbot://jobs/band-a", name="band_a_shortlist", description="Current Band A shortlisted job opportunities")
def resource_band_a() -> str:
    jobs = services.list_jobs(band="A")
    return json.dumps(jobs, indent=2)


@server.resource("jobbot://facts", name="candidate_facts", description="Candidate verified background, skills, and projects")
def resource_candidate_facts() -> str:
    return services.get_candidate_facts_text()


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
