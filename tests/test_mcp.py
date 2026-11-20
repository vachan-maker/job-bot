import json
import pytest
from jobbot.mcp_server import (
    server, get_pipeline_status, list_jobs, get_job_details,
    search_jobs, suppress_company, get_candidate_facts,
    resource_pipeline_status, resource_band_a, resource_candidate_facts,
    prompt_review_and_tailor
)

@pytest.mark.anyio
async def test_mcp_server_initialization():
    assert server.name == "jobbot"
    tools = await server.list_tools()
    tool_names = [t.name for t in tools]
    assert "get_pipeline_status" in tool_names
    assert "list_jobs" in tool_names
    assert "get_job_details" in tool_names
    assert "search_jobs" in tool_names
    assert "tailor_resume" in tool_names
    assert "manual_apply" in tool_names
    assert "draft_application" in tool_names
    assert "approve_application" in tool_names
    assert "send_application" in tool_names
    assert "suppress_company" in tool_names

def test_mcp_get_pipeline_status():
    status = get_pipeline_status()
    assert "pipeline_states" in status
    assert "score_bands" in status
    assert isinstance(status["pipeline_states"], dict)
    assert isinstance(status["score_bands"], dict)

def test_mcp_list_and_search_jobs():
    jobs = list_jobs(limit=5)
    assert isinstance(jobs, list)
    if jobs:
        j = jobs[0]
        assert "id" in j
        assert "company" in j
        assert "title" in j
        assert "score" in j

    search_res = search_jobs("Developer", limit=5)
    assert isinstance(search_res, list)

def test_mcp_resources_and_prompts():
    status_json = resource_pipeline_status()
    status_dict = json.loads(status_json)
    assert "pipeline_states" in status_dict

    band_a_json = resource_band_a()
    assert isinstance(json.loads(band_a_json), list)

    prompt_text = prompt_review_and_tailor()
    assert "Band A" in prompt_text

def test_mcp_suppress_company():
    res = suppress_company("MCP Test Company Inc", reason="mcp_test")
    assert res["success"] is True
    assert res["name_key"] == "MCP_TEST_COMPANY"
