import pytest
from jobbot.normalize import (
    normalize_company_name, normalize_title, classify_location,
    extract_emails, extract_subject_override, compute_hashes
)

def test_company_normalization():
    assert normalize_company_name("2Base Technologies Pvt Ltd") == "2BASE"
    assert normalize_company_name("TRAINONEX SOLUTIONS (P) Ltd") == "TRAINONEX_SOLUTIONS"
    assert normalize_company_name("Google LLC") == "GOOGLE"
    assert normalize_company_name("Acme Private Limited") == "ACME"
    assert normalize_company_name("Medowa Global LLP") == "MEDOWA_GLOBAL"

def test_title_normalization():
    norm = normalize_title("Junior Laravel Developer (Fresher)")
    assert "junior" not in norm
    assert "fresher" not in norm
    assert "laravel" in norm
    assert "developer" in norm

def test_location_classification():
    assert classify_location("Kochi, Kerala") == "kochi"
    assert classify_location("Technopark, Trivandrum") == "tvm"
    assert classify_location("Remote / WFH") == "remote"
    assert classify_location("Work from home") == "remote"
    assert classify_location("") == "unspecified"
    assert classify_location(None) == "unspecified"
    assert classify_location("Bengaluru, Karnataka") == "other"
    assert classify_location("Chennai") == "other"
    assert classify_location("Kerala, India") == "kerala"

def test_email_extraction_and_priority():
    text = """
    Please contact us at info@example.com or reach out directly to hr@example.com.
    Do not reply to noreply@example.com. Also ignored banner_logo@example.png.
    """
    emails = extract_emails(text)
    assert len(emails) >= 2
    # hr@ must come before info@
    assert emails[0] == "hr@example.com"
    # Image filename must not be in emails
    assert not any(e.endswith(".png") for e in emails)

def test_subject_override_extraction():
    text1 = 'Please send your resume with subject: "Application for Junior Python Developer" to hr@test.com'
    assert extract_subject_override(text1) == "Application for Junior Python Developer"

    text2 = 'Email your CV with subject: PHP Trainee - Kochi'
    assert extract_subject_override(text2) == "PHP Trainee - Kochi"

    text3 = 'Just a regular job description without specific subject requirements.'
    assert extract_subject_override(text3) is None

def test_compute_hashes():
    h1, k1 = compute_hashes("MEDOWA", "laravel developer", "Looking for Laravel dev...")
    h2, k2 = compute_hashes("MEDOWA", "laravel developer", "Looking for Laravel dev...")
    assert h1 == h2
    assert k1 == k2
    assert len(h1) == 40
    assert len(k1) == 40
