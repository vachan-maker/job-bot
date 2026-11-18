import re
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

def extract_pdf_info(pdf_path: Path) -> Dict[str, str]:
    res = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"pdfinfo failed: {res.stderr}")
    info = {}
    for line in res.stdout.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            info[k.strip()] = v.strip()
    return info

def extract_pdf_text(pdf_path: Path) -> str:
    res = subprocess.run(["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"pdftotext failed: {res.stderr}")
    return res.stdout

def get_candidate_facts_path(preferred: Optional[Path] = None) -> Optional[Path]:
    """Find the candidate facts file, prioritizing facts.local.md."""
    if preferred and preferred.exists():
        return preferred
    for candidate in [
        Path("profile/facts.local.md"),
        Path("profile/facts.md"),
        Path("profile/facts.example.md")
    ]:
        if candidate.exists():
            return candidate
    return None

def validate_pdf(
    pdf_path: Path,
    facts_path: Path = None,
    build_log: str = "",
    forbidden_terms: List[str] = None
) -> Tuple[bool, Dict[str, Any]]:
    forbidden_terms = forbidden_terms or [
        "Selenium", "Cypress", "STLC", "JIRA", "Kubernetes", "CI/CD", "Terraform", "TestRail"
    ]
    results: Dict[str, Any] = {}
    passed_all = True

    # 1. Pages & Page Size
    try:
        info = extract_pdf_info(pdf_path)
        pages = int(info.get("Pages", "0"))
        page_size = info.get("Page size", "")

        is_one_page = (pages == 1)
        # A4 is 595 x 842 pts (approx 595.x x 841.x or 595 x 842)
        is_a4 = ("595" in page_size and "84" in page_size)

        if not is_one_page:
            passed_all = False
            results["pages"] = {"pass": False, "detail": f"Expected 1 page, got {pages}"}
        else:
            results["pages"] = {"pass": True, "detail": "1 page"}

        if not is_a4:
            passed_all = False
            results["size"] = {"pass": False, "detail": f"Expected A4 (595x842 pts), got {page_size}"}
        else:
            results["size"] = {"pass": True, "detail": f"A4 ({page_size})"}
    except Exception as e:
        passed_all = False
        results["pages"] = {"pass": False, "detail": str(e)}
        results["size"] = {"pass": False, "detail": str(e)}

    # Extract text from PDF
    try:
        pdf_text = extract_pdf_text(pdf_path)
    except Exception as e:
        return False, {"error": f"Failed to extract text: {e}"}

    # 2. Ligatures check
    ligature_glyphs = ["\ufb01", "\ufb02", "\ufb00", "\ufb03", "\ufb04", "ﬂ", "ﬁ", "ﬀ", "ﬃ"]
    found_ligatures = [g for g in ligature_glyphs if g in pdf_text]
    if found_ligatures:
        passed_all = False
        results["ligatures"] = {"pass": False, "detail": f"Found ligatures: {found_ligatures}"}
    else:
        results["ligatures"] = {"pass": True, "detail": "None"}

    # 3. Forbidden terms check
    found_forbidden = []
    for term in forbidden_terms:
        # Match as whole word / regex
        if re.search(rf'\b{re.escape(term)}\b', pdf_text, re.I):
            found_forbidden.append(term)
    if found_forbidden:
        passed_all = False
        results["forbidden_terms"] = {"pass": False, "detail": f"Found forbidden terms: {found_forbidden}"}
    else:
        results["forbidden_terms"] = {"pass": True, "detail": "None"}

    # 4. Fact diff check
    facts_text = ""
    fpath = get_candidate_facts_path(facts_path)
    if fpath:
        facts_text = fpath.read_text(encoding="utf-8")

    # Check 4-digit years in PDF
    years = set(re.findall(r'\b(20\d\d)\b', pdf_text))
    unknown_years = [y for y in years if y not in facts_text]

    # Check CGPA patterns — only flag X.XX numbers that appear near GPA/CGPA keywords,
    # to avoid false positives from version numbers, percentages, etc.
    cgpa_context_pattern = re.compile(
        r'(?:cgpa|gpa|grade\s+point|score)[^\n]{0,40}?(\d\.\d\d)', re.I
    )
    cgpa_matches = set(cgpa_context_pattern.findall(pdf_text))
    unknown_cgpa = [c for c in cgpa_matches if c not in facts_text]

    if unknown_years or unknown_cgpa:
        passed_all = False
        results["fact_diff"] = {
            "pass": False,
            "detail": f"Unconfirmed facts in PDF - Years: {unknown_years}, CGPA: {unknown_cgpa}"
        }
    else:
        results["fact_diff"] = {"pass": True, "detail": "All dates & numbers verified"}

    # 5. Build log check
    if build_log:
        bad_logs = []
        for line in build_log.splitlines():
            if any(w in line for w in ["Overfull", "Underfull", "LaTeX Warning"]):
                bad_logs.append(line.strip())
        if bad_logs:
            passed_all = False
            results["build_log"] = {"pass": False, "detail": f"{len(bad_logs)} warnings: {bad_logs[:3]}"}
        else:
            results["build_log"] = {"pass": True, "detail": "Clean build log"}
    else:
        results["build_log"] = {"pass": True, "detail": "No log provided or clean"}

    return passed_all, results
