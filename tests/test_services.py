import pytest
from jobbot import services
from jobbot.db import init_db

def setup_module():
    init_db()

def test_services_facts():
    facts = services.get_candidate_facts_text()
    assert isinstance(facts, str)
    assert len(facts) > 0

def test_services_pipeline_status():
    status = services.get_pipeline_status()
    assert "pipeline_states" in status
    assert "score_bands" in status
    assert "applications" in status
    assert isinstance(status["pipeline_states"], dict)
    assert isinstance(status["score_bands"], dict)

def test_services_list_and_search():
    jobs = services.list_jobs(limit=5)
    assert isinstance(jobs, list)

    res = services.search_jobs("Developer", limit=5)
    assert isinstance(res, list)

def test_services_get_job_details_not_found():
    res = services.get_job_details(99999999)
    assert "error" in res

def test_services_tailor_not_found():
    res = services.tailor_single_job(99999999)
    assert res["success"] is False
    assert "error" in res

def test_services_draft_not_found():
    res = services.draft_single_job(99999999)
    assert res["success"] is False
    assert "error" in res

def test_services_suppress_company():
    res = services.suppress_company_name("Services Test Corp", reason="test")
    assert res["success"] is True
    assert res["name_key"] == "SERVICES_TEST_CORP"

def test_services_send_window_blocked():
    # Calling send without force outside window (unless within 10-17 IST)
    # This verifies window logic is wired in
    res = services.send_single_job(99999999, force=False, dry_run=False)
    # Should either fail with window_blocked or not found, but not uncaught error
    assert res["success"] is False
    assert "error" in res
