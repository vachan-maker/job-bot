import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import yaml
from dotenv import load_dotenv

from jobbot.models import Job
from jobbot.normalize import normalize_company_name
from jobbot.validate import validate_pdf

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

def call_gemini_tailor(prompt: str) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-3.8-flash")
        resp = model.generate_content(prompt)
        text = resp.text.strip()
        # Clean markdown codeblocks if LLM wrapped it
        if text.startswith("```"):
            text = re.sub(r'^```(?:latex|tex)?\n', '', text)
            text = re.sub(r'\n```$', '', text)
        return text.strip()
    except Exception as e:
        print(f"Gemini API tailoring failed: {e}")
        return None

def compile_latex(dir_path: Path, tectonic_bin: Path) -> Tuple[bool, str]:
    tex_path = dir_path / "resume.tex"
    if not tex_path.exists():
        return False, "resume.tex not found"

    cmd = [str(tectonic_bin), "-X", "compile", "resume.tex"]
    res = subprocess.run(cmd, cwd=dir_path, capture_output=True, text=True)
    combined_log = (res.stdout or "") + "\n" + (res.stderr or "")

    return (res.returncode == 0), combined_log

def tailor_job(job: Job, config: Dict[str, Any], facts_path: Path = Path("profile/facts.md")) -> Tuple[bool, Optional[Path], Dict[str, Any]]:
    resume_root = Path(config.get("candidate", {}).get("resume_root", "~/Resume"))
    tectonic_path = Path(os.path.expanduser(config.get("tailoring", {}).get("tectonic", "~/.local/bin/tectonic")))
    forbidden_terms = config.get("tailoring", {}).get("forbidden_terms", [])

    base_dir = select_base_resume(job, resume_root)
    base_tex_path = base_dir / "resume.tex"
    base_tex_content = base_tex_path.read_text(encoding="utf-8")

    out_dir = create_output_directory(job, resume_root)
    target_tex = out_dir / "resume.tex"

    facts_text = facts_path.read_text(encoding="utf-8") if facts_path.exists() else ""
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
        tailored_tex = call_gemini_tailor(prompt)

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
