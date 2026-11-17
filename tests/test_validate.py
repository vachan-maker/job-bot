from pathlib import Path
from jobbot.validate import validate_pdf

def test_forbidden_terms_and_build_log(monkeypatch):
    # Mock extract_pdf_info and extract_pdf_text so test does not require building real PDF
    monkeypatch.setattr("jobbot.validate.extract_pdf_info", lambda p: {"Pages": "1", "Page size": "595 x 842 pts"})
    monkeypatch.setattr("jobbot.validate.extract_pdf_text", lambda p: "Alex Doe. Skills: Selenium, Playwright, Python.")

    valid, results = validate_pdf(Path("dummy.pdf"), forbidden_terms=["Selenium", "Cypress"])
    assert not valid
    assert results["forbidden_terms"]["pass"] is False
    assert "Selenium" in results["forbidden_terms"]["detail"]

def test_ligature_detection(monkeypatch):
    monkeypatch.setattr("jobbot.validate.extract_pdf_info", lambda p: {"Pages": "1", "Page size": "595 x 842 pts"})
    monkeypatch.setattr("jobbot.validate.extract_pdf_text", lambda p: "Worked on automated ﬂow and full-stack systems.")

    valid, results = validate_pdf(Path("dummy.pdf"))
    assert not valid
    assert results["ligatures"]["pass"] is False

def test_pages_and_size_validation(monkeypatch):
    monkeypatch.setattr("jobbot.validate.extract_pdf_info", lambda p: {"Pages": "2", "Page size": "612 x 792 pts"})
    monkeypatch.setattr("jobbot.validate.extract_pdf_text", lambda p: "Alex Doe resume content.")

    valid, results = validate_pdf(Path("dummy.pdf"))
    assert not valid
    assert results["pages"]["pass"] is False
    assert results["size"]["pass"] is False

def test_build_log_warnings(monkeypatch):
    monkeypatch.setattr("jobbot.validate.extract_pdf_info", lambda p: {"Pages": "1", "Page size": "595 x 842 pts"})
    monkeypatch.setattr("jobbot.validate.extract_pdf_text", lambda p: "Clean text.")

    valid, results = validate_pdf(Path("dummy.pdf"), build_log="Underfull \\hbox (badness 10000) in paragraph at lines 42--43")
    assert not valid
    assert results["build_log"]["pass"] is False
