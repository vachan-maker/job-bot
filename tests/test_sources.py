import json
from pathlib import Path
from jobbot.sources.infopark import InfoparkSource
from jobbot.sources.technopark import TechnoparkSource
from jobbot.sources.ulcyberpark import ULCyberparkSource
from jobbot.sources.smartcity import SmartCitySource
from jobbot.models import Job

FIXTURES_DIR = Path(__file__).parent / "fixtures"

def test_infopark_list_parsing():
    html_file = FIXTURES_DIR / "infopark_list_p1.html"
    assert html_file.exists()

    source = InfoparkSource()
    jobs = source.parse_list_page(html_file.read_text(encoding="utf-8"))

    assert len(jobs) >= 20
    for job in jobs:
        assert job.source == "infopark"
        assert job.source_job_id
        assert job.url.startswith("https://infopark.in")
        assert job.company
        assert job.title

def test_infopark_detail_parsing():
    detail_file = FIXTURES_DIR / "infopark_detail_26855.html"
    assert detail_file.exists()

    source = InfoparkSource()
    dummy_job = Job(
        source="infopark",
        source_job_id="26855",
        url="https://infopark.in/company-jobs/details/428/26855",
        company="Test Company",
        title="Software Engineer"
    )

    enriched = source.parse_detail_page(dummy_job, detail_file.read_text(encoding="utf-8"))
    assert enriched.jd_text
    assert enriched.jd_hash
    assert enriched.dedupe_key

def test_ulcyberpark_list_parsing():
    html_file = FIXTURES_DIR / "ulcyberpark_list.html"
    assert html_file.exists()

    source = ULCyberparkSource()
    jobs = source.parse_list_page(html_file.read_text(encoding="utf-8"))

    assert len(jobs) >= 5
    for job in jobs:
        assert job.source == "ulcyberpark"
        assert job.source_job_id
        assert job.url.startswith("https://www.ulcyberpark.com")
        assert job.company
        assert job.title
        assert job.location_class == "kerala"

def test_ulcyberpark_detail_parsing():
    detail_file = FIXTURES_DIR / "ulcyberpark_detail_1703.html"
    assert detail_file.exists()

    source = ULCyberparkSource()
    dummy_job = Job(
        source="ulcyberpark",
        source_job_id="1703",
        url="https://www.ulcyberpark.com/jobs/job_vacancy?job_id=1703",
        company="Tranetech Software Solutions",
        title="Junior Quality Analyst"
    )

    enriched = source.parse_detail_page(dummy_job, detail_file.read_text(encoding="utf-8"))
    assert enriched.jd_text
    assert enriched.jd_hash
    assert enriched.dedupe_key
    assert len(enriched.emails) > 0
    # hr.admin@tranetech.ae should be present and prioritized
    assert any("tranetech" in e for e in enriched.emails)

def test_smartcity_list_parsing():
    html_file = FIXTURES_DIR / "smartcity_list.html"
    assert html_file.exists()

    source = SmartCitySource()
    jobs = source.parse_list_page(html_file.read_text(encoding="utf-8"))

    assert len(jobs) >= 15
    for job in jobs:
        assert job.source == "smartcity"
        assert job.source_job_id
        assert job.url.startswith("https://smartcity-kochi.in")
        assert job.company
        assert job.title
        assert job.location_class == "kochi"

def test_smartcity_detail_parsing():
    detail_file = FIXTURES_DIR / "smartcity_detail_8471.html"
    assert detail_file.exists()

    source = SmartCitySource()
    dummy_job = Job(
        source="smartcity",
        source_job_id="8471",
        url="https://smartcity-kochi.in/2026/07/cyncly-smartcity-kochi-senior-service-desk-engineer-l2/",
        company="Cyncly",
        title="Senior service desk Engineer (L2)"
    )

    enriched = source.parse_detail_page(dummy_job, detail_file.read_text(encoding="utf-8"))
    assert enriched.jd_text
    assert enriched.jd_hash
    assert enriched.dedupe_key
    assert len(enriched.emails) > 0
    assert any("cyncly.com" in e for e in enriched.emails)
    assert isinstance(enriched.emails, list)

def test_technopark_list_parsing():
    json_file = FIXTURES_DIR / "tp_list_p1.json"
    assert json_file.exists()

    source = TechnoparkSource()
    data = json.loads(json_file.read_text(encoding="utf-8"))
    pagination = data if "last_page" in data else data.get("data", {})
    items = pagination.get("data", []) if "data" in pagination else data.get("data", [])

    assert len(items) > 0
    jobs = [source.parse_list_item(item) for item in items if source.parse_list_item(item)]

    assert len(jobs) >= 15
    for job in jobs:
        assert job.source == "technopark"
        assert job.source_job_id
        assert job.company
        assert job.title
        assert job.url.startswith("https://technopark.in")

def test_technopark_detail_parsing():
    detail_file = next(FIXTURES_DIR.glob("tp_detail_*.html"), None)
    assert detail_file is not None and detail_file.exists()

    source = TechnoparkSource()
    dummy_job = Job(
        source="technopark",
        source_job_id="34276",
        url="https://technopark.in/job-details/34276",
        company="Technopark Company",
        title="Software Developer"
    )

    enriched = source.parse_detail_page(dummy_job, detail_file.read_text(encoding="utf-8"))
    assert enriched.jd_text
    assert enriched.jd_hash
    assert enriched.dedupe_key

def test_ulcyberpark_list_parsing():
    html_file = FIXTURES_DIR / "ulcyberpark_list.html"
    assert html_file.exists()

    source = ULCyberparkSource()
    jobs = source.parse_list_page(html_file.read_text(encoding="utf-8"))

    assert len(jobs) >= 5
    for job in jobs:
        assert job.source == "ulcyberpark"
        assert job.source_job_id
        assert job.url.startswith("https://www.ulcyberpark.com")
        assert job.company
        assert job.title
        assert job.location_class == "kerala"

def test_ulcyberpark_detail_parsing():
    detail_file = FIXTURES_DIR / "ulcyberpark_detail_1703.html"
    assert detail_file.exists()

    source = ULCyberparkSource()
    dummy_job = Job(
        source="ulcyberpark",
        source_job_id="1703",
        url="https://www.ulcyberpark.com/jobs/job_vacancy?job_id=1703",
        company="Tranetech Software Solutions",
        title="Junior Quality Analyst"
    )

    enriched = source.parse_detail_page(dummy_job, detail_file.read_text(encoding="utf-8"))
    assert enriched.jd_text
    assert enriched.jd_hash
    assert enriched.dedupe_key
    assert len(enriched.emails) > 0
    # hr.admin@tranetech.ae should be present and prioritized
    assert any("tranetech" in e for e in enriched.emails)

def test_smartcity_list_parsing():
    html_file = FIXTURES_DIR / "smartcity_list.html"
    assert html_file.exists()

    source = SmartCitySource()
    jobs = source.parse_list_page(html_file.read_text(encoding="utf-8"))

    assert len(jobs) >= 15
    for job in jobs:
        assert job.source == "smartcity"
        assert job.source_job_id
        assert job.url.startswith("https://smartcity-kochi.in")
        assert job.company
        assert job.title
        assert job.location_class == "kochi"

def test_smartcity_detail_parsing():
    detail_file = FIXTURES_DIR / "smartcity_detail_8471.html"
    assert detail_file.exists()

    source = SmartCitySource()
    dummy_job = Job(
        source="smartcity",
        source_job_id="8471",
        url="https://smartcity-kochi.in/2026/07/cyncly-smartcity-kochi-senior-service-desk-engineer-l2/",
        company="Cyncly",
        title="Senior service desk Engineer (L2)"
    )

    enriched = source.parse_detail_page(dummy_job, detail_file.read_text(encoding="utf-8"))
    assert enriched.jd_text
    assert enriched.jd_hash
    assert enriched.dedupe_key
    assert len(enriched.emails) > 0
    assert any("cyncly.com" in e for e in enriched.emails)
