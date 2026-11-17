import tempfile
from pathlib import Path
from jobbot.models import Job
from jobbot.db import init_db, upsert_job, get_connection

def test_scrape_upsert_idempotency():
    with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
        db_path = Path(tmp.name)
        init_db(db_path)

        job1 = Job(
            source="infopark",
            source_job_id="999",
            url="https://infopark.in/job/999",
            company="Test Inc",
            title="Python Developer",
            jd_text="First version of JD text"
        )

        id1 = upsert_job(job1, db_path=db_path)
        id2 = upsert_job(job1, db_path=db_path)

        assert id1 == id2

        conn = get_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) as cnt FROM jobs")
        count = cursor.fetchone()["cnt"]
        conn.close()

        assert count == 1
