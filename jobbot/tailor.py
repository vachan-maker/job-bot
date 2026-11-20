import os
import re
import shutil
import subprocess
import json
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import yaml
from dotenv import load_dotenv

from jobbot.models import Job
from jobbot.normalize import normalize_company_name
from jobbot.validate import validate_pdf, get_candidate_facts_path

load_dotenv()

ROLE_FAMILY_BASE_MAP = {
    "php_laravel": ["MEDOWA_GLOBAL_LARAVEL_PHP_DEVELOPER"],
    "qa_testing": ["SCALGO_QA_Intern", "AUGUSTA_HITECH_QA_ENGINEER"],
    "devops_cloud": [
        "LOGIOLOGY_JUNIOR_CLOUD_DEVOPS_ENGINEER",
        "COMPRINNO_DEVOPS_ENGINEER_INTERN",
        "ZENOCLOUD_CLOUD_DEVOPS_INTERN"
    ],
    "python_django": ["IVBM_JUNIOR_DEVELOPER_PYTHON_DJANGO"],
    "fullstack_js": ["THALES_SOFTWARE_ENGINEER"],
    "ai_ml": ["LATENTFORCE_RESEARCH_INTERN_AGENTIC_AI"]
}

def select_base_resume(job: Job, resume_root: Path) -> Path:
    family = job.role_family or "fullstack_js"
    candidates = ROLE_FAMILY_BASE_MAP.get(family, ["THALES_SOFTWARE_ENGINEER"])

    # Location-based tie-break for DevOps
    if family == "devops_cloud":
        if job.location_class == "kochi":
            candidates = ["LOGIOLOGY_JUNIOR_CLOUD_DEVOPS_ENGINEER", "COMPRINNO_DEVOPS_ENGINEER_INTERN", "ZENOCLOUD_CLOUD_DEVOPS_INTERN"]
        else:
            candidates = ["ZENOCLOUD_CLOUD_DEVOPS_INTERN", "COMPRINNO_DEVOPS_ENGINEER_INTERN", "LOGIOLOGY_JUNIOR_CLOUD_DEVOPS_ENGINEER"]

    # Choose candidate folder with existing resume.tex
    for cand in candidates:
        cand_dir = resume_root / cand
        if (cand_dir / "resume.tex").exists():
            return cand_dir

    # Fallback to first existing dir in resume_root
    for cand in candidates:
        if (resume_root / cand).exists():
            return resume_root / cand

    # Default to whatever folder has a resume.tex
    for p in resume_root.iterdir():
        if p.is_dir() and (p / "resume.tex").exists():
            return p

    raise FileNotFoundError(f"No suitable base resume found in {resume_root}")

def create_output_directory(job: Job, resume_root: Path) -> Path:
    company_key = normalize_company_name(job.company) or "UNKNOWN"
    role_slug = re.sub(r'[^A-Za-z0-9]', '_', job.title.upper()).strip('_')[:40]
    folder_name = f"{company_key}_{role_slug}"
    out_dir = resume_root / folder_name

    if out_dir.exists():
        # Check if already tailored for this specific job
        # If different role or duplicate, check for _2
        counter = 2
        while out_dir.exists() and (out_dir / "resume.pdf").exists():
            out_dir = resume_root / f"{folder_name}_{counter}"
            counter += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir

def _clean_llm_text(text: str) -> str:
    """Remove markdown code fences when a model wraps plain output."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r'^```(?:latex|tex|json)?\n', '', text, flags=re.I)
        text = re.sub(r'\n```$', '', text)
    return text.strip()


def _call_gemini_model(prompt: str, model_name: str) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.3),
        )
        return _clean_llm_text(resp.text)
    except Exception as e:
        print(f"Gemini API tailoring failed for {model_name}: {e}")
        return None


def call_gemini_tailor(prompt: str) -> Optional[str]:
    """Call the primary Gemini model configured for tailoring."""
    return _call_gemini_model(prompt, os.getenv("GEMINI_MODEL", "gemini-3.8-flash"))


def call_gemini_fallback_tailor(prompt: str) -> Optional[str]:
    """Call a second Gemini model with the same API key if the primary fails."""
    return _call_gemini_model(
        prompt,
        os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite"),
    )


def call_llm_tailor(prompt: str) -> Optional[str]:
    """Use the primary Gemini model, then a lower-demand Gemini fallback."""
    if not os.getenv("GEMINI_API_KEY"):
        return None

    result = call_gemini_tailor(prompt)
    if result:
        return result

    primary_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.1-flash-lite")
    if fallback_model == primary_model:
        return None

    print(f"Retrying Gemini tailoring with fallback model {fallback_model}")
    return call_gemini_fallback_tailor(prompt)


def _basic_clean_job_description(raw_text: str) -> str:
    """Remove copied-page markup/noise when an LLM is unavailable."""
    soup = BeautifulSoup(raw_text or "", "html.parser")
    for element in soup(["script", "style", "nav", "header", "footer", "aside", "form", "button"]):
        element.decompose()
    text = soup.get_text("\n")
    lines = []
    previous_blank = False
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip(" \\t•·")
        if not line:
            if not previous_blank and lines:
                lines.append("")
            previous_blank = True
            continue
        if re.match(r"^(share|print|apply now|sign in|login|subscribe|cookie|privacy policy)\b", line, re.I):
            continue
        lines.append(line)
        previous_blank = False
    return "\n".join(lines).strip()


def clean_job_description(raw_text: str) -> str:
    """Use the configured LLM to turn pasted page content into a concise JD."""
    fallback = _basic_clean_job_description(raw_text)
    if not fallback or not os.getenv("GEMINI_API_KEY"):
        return fallback

    prompt = f"""Clean and structure the following pasted job-page content for resume tailoring.
Remove navigation, cookie notices, duplicate text, social/share controls, and unrelated company marketing.
Keep only job title (if present), responsibilities, required/preferred skills, experience, education,
location, employment type, and application instructions. Preserve facts and wording; do not invent or
summarize away requirements. Return JSON only in this shape: {{\"job_description\": \"...\"}}.

PASTED CONTENT:
{raw_text}
"""
    cleaned = call_llm_tailor(prompt)
    if cleaned:
        try:
            parsed = json.loads(cleaned)
            cleaned = parsed.get("job_description", "")
        except (json.JSONDecodeError, AttributeError):
            cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned.strip(), flags=re.I)
        if cleaned.strip():
            return _basic_clean_job_description(cleaned)
    return fallback

def compile_latex(dir_path: Path, tectonic_bin: Path) -> Tuple[bool, str]:
    tex_path = dir_path / "resume.tex"
    if not tex_path.exists():
        return False, "resume.tex not found"

    cmd = [str(tectonic_bin), "-X", "compile", "resume.tex"]
    res = subprocess.run(cmd, cwd=dir_path, capture_output=True, text=True)
    combined_log = (res.stdout or "") + "\n" + (res.stderr or "")

    return (res.returncode == 0), combined_log

def tailor_job(job: Job, config: Dict[str, Any], facts_path: Path = None) -> Tuple[bool, Optional[Path], Dict[str, Any]]:
    resume_root = Path(config.get("candidate", {}).get("resume_root", "~/Resume"))
    tectonic_path = Path(os.path.expanduser(config.get("tailoring", {}).get("tectonic", "~/.local/bin/tectonic")))
    forbidden_terms = config.get("tailoring", {}).get("forbidden_terms", [])

    base_dir = select_base_resume(job, resume_root)
    base_tex_path = base_dir / "resume.tex"
    base_tex_content = base_tex_path.read_text(encoding="utf-8")

    out_dir = create_output_directory(job, resume_root)
    target_tex = out_dir / "resume.tex"

    fpath = get_candidate_facts_path(facts_path)
    facts_text = fpath.read_text(encoding="utf-8") if fpath else ""
    prompt_template_path = Path("profile/tailor_prompt.md")
    prompt_template = prompt_template_path.read_text(encoding="utf-8") if prompt_template_path.exists() else ""

    # Attempt LLM edit if key is present; otherwise copy base
    tailored_tex = None
    if os.getenv("GEMINI_API_KEY") and prompt_template:
        prompt = (
            prompt_template
            .replace("{facts}", facts_text)
            .replace("{jd}", job.jd_text or job.title)
            .replace("{tex}", base_tex_content)
        )
        tailored_tex = call_llm_tailor(prompt)

    if not tailored_tex:
        # Fallback to base resume with updated metadata comments
        tailored_tex = base_tex_content

    # Sanitize forbidden terms if present in base template
    for ft in forbidden_terms:
        tailored_tex = re.sub(rf'\b{re.escape(ft)}\b', '', tailored_tex)
    tailored_tex = re.sub(r',\s*,', ',', tailored_tex)
    tailored_tex = re.sub(r',\s*\}', '}', tailored_tex)

    target_tex.write_text(tailored_tex, encoding="utf-8")

    # Compile with Tectonic
    success, build_log = compile_latex(out_dir, tectonic_path)
    if not success:
        # Retry once with base_tex_content directly
        target_tex.write_text(base_tex_content, encoding="utf-8")
        success, build_log = compile_latex(out_dir, tectonic_path)
        if not success:
            return False, None, {"error": "Compilation failed", "log": build_log}

    pdf_path = out_dir / "resume.pdf"
    if not pdf_path.exists():
        return False, None, {"error": "resume.pdf was not produced"}

    # Validate PDF
    valid, validation_results = validate_pdf(
        pdf_path,
        facts_path=facts_path,
        build_log=build_log,
        forbidden_terms=forbidden_terms
    )

    if not valid:
        # If LLM tailoring caused validation failure (e.g. page count overflow), fallback to sanitized base template
        sanitized_base = base_tex_content
        for ft in forbidden_terms:
            sanitized_base = re.sub(rf'\b{re.escape(ft)}\b', '', sanitized_base)
        sanitized_base = re.sub(r',\s*,', ',', sanitized_base)
        sanitized_base = re.sub(r',\s*\}', '}', sanitized_base)
        target_tex.write_text(sanitized_base, encoding="utf-8")
        s, bl = compile_latex(out_dir, tectonic_path)
        if s and pdf_path.exists():
            v, vr = validate_pdf(
                pdf_path,
                facts_path=facts_path,
                build_log=bl,
                forbidden_terms=forbidden_terms
            )
            if v:
                valid = True
                validation_results = vr
                build_log = bl

    if not valid:
        return False, pdf_path, {"validation": validation_results}

    # Rename final PDF to standard format: <Candidate>-<Company>-<Role>.pdf
    candidate_name = config.get("candidate", {}).get("name", "Resume")
    safe_candidate = re.sub(r'[^a-zA-Z0-9]', '', candidate_name)
    safe_company = re.sub(r'[^a-zA-Z0-9]', '', job.company)
    safe_role = re.sub(r'[^a-zA-Z0-9]', '', job.title)
    final_pdf_name = f"{safe_candidate}-{safe_company}-{safe_role}.pdf"
    final_pdf_path = out_dir / final_pdf_name
    shutil.copy2(pdf_path, final_pdf_path)

    # Clean build artifacts
    for f in out_dir.iterdir():
        if f.suffix in [".log", ".aux", ".out", ".png", ".txt"] and f.name != "resume.tex":
            try:
                f.unlink()
            except Exception:
                pass

    return True, final_pdf_path, {"base_used": base_dir.name, "validation": validation_results}
