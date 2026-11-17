from datetime import date, timedelta
from jobbot.models import Job
from jobbot.rank import check_hard_filters, calculate_score, load_config, load_skills

def test_walk_in_drive_hard_filter():
    config = load_config()
    job = Job(
        source="infopark",
        source_job_id="101",
        url="https://infopark.in/test",
        company="TechCorp",
        title="WALK IN DRIVE @ Kochi - QA Engineers",
        location_raw="Kochi",
        location_class="kochi",
        emails=["hr@techcorp.com"],
        jd_text="Walk in drive on Saturday."
    )
    passed, reason = check_hard_filters(job, config)
    assert not passed
    assert "Walk-in" in reason

def test_seniority_reject_hard_filter():
    config = load_config()
    job = Job(
        source="infopark",
        source_job_id="102",
        url="https://infopark.in/test",
        company="TechCorp",
        title="Senior Lead Software Architect",
        location_raw="Kochi",
        location_class="kochi",
        emails=["hr@techcorp.com"],
        jd_text="Requirements: 8+ years experience."
    )
    passed, reason = check_hard_filters(job, config)
    assert not passed
    assert "Seniority rejected" in reason

def test_experience_reject_hard_filter():
    config = load_config()
    job = Job(
        source="technopark",
        source_job_id="103",
        url="https://technopark.in/test",
        company="TechCorp",
        title="Software Engineer",
        location_raw="Trivandrum",
        location_class="tvm",
        emails=["hr@techcorp.com"],
        jd_text="Candidate must possess at least 4+ years of professional development experience."
    )
    passed, reason = check_hard_filters(job, config)
    assert not passed
    assert "Experience requirement too high" in reason

def test_location_reject_hard_filter():
    config = load_config()
    job = Job(
        source="technopark",
        source_job_id="104",
        url="https://technopark.in/test",
        company="TechCorp",
        title="Junior Developer",
        location_raw="Bengaluru",
        location_class="other",
        emails=["hr@techcorp.com"],
        jd_text="Work in Bangalore office."
    )
    passed, reason = check_hard_filters(job, config)
    assert not passed
    assert "Location rejected" in reason

def test_scoring_band_a_golden():
    config = load_config()
    skills_cfg = load_skills()

    job = Job(
        source="infopark",
        source_job_id="201",
        url="https://infopark.in/test/201",
        company="BrandNewCorp",
        title="Junior Laravel Developer (Fresher)",
        location_raw="Kochi",
        location_class="kochi",
        posted_on=date.today(),
        emails=["hr@brandnewcorp.com"],
        jd_text="""
        We are hiring a Junior Laravel Developer.
        Required Skills:
        - PHP, Laravel, MySQL, REST API, Eloquent, Blade, Composer, HTML, CSS, JavaScript, Git.
        - Experience with Sanctum authentication and MVC architecture.
        - Strong OOP fundamentals.
        Immediate joining required.
        """
    )
    score_res = calculate_score(job, config, skills_cfg)
    assert score_res.total >= 70
    assert score_res.band == "A"
    assert score_res.role_family == "php_laravel"
    assert score_res.components["skills"] > 30
    assert score_res.components["title_seniority"] == 20
    assert score_res.components["location"] == 10
    assert score_res.components["recency"] == 10
