import time
from pathlib import Path
from jobbot.db import get_connection, row_to_job, upsert_job
from jobbot.sources.infopark import InfoparkSource
from jobbot.sources.technopark import TechnoparkSource
from jobbot.rank import load_config, check_preliminary_title_filters

def main():
    config = load_config()
    info_src = InfoparkSource()
    tp_src = TechnoparkSource()

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs WHERE jd_text IS NULL OR jd_text = ''")
    rows = cursor.fetchall()

    print(f"Total jobs to inspect: {len(rows)}")
    fetched = 0
    skipped = 0

    for idx, r in enumerate(rows):
        job = row_to_job(r)
        passed, reason = check_preliminary_title_filters(job, config)
        if not passed:
            cursor.execute(
                "UPDATE jobs SET state = 'skipped', skip_reason = ? WHERE id = ?",
                (reason, job.id)
            )
            skipped += 1
            continue

        try:
            if job.source == "infopark":
                enriched = info_src.fetch_detail(job)
            else:
                enriched = tp_src.fetch_detail(job)

            cursor.execute(
                """
                UPDATE jobs SET
                    location_raw = ?, location_class = ?, emails = ?, jd_text = ?,
                    jd_hash = ?, dedupe_key = ?, subject_override = ?, is_walk_in = ?,
                    state = 'new'
                WHERE id = ?
                """,
                (
                    enriched.location_raw, enriched.location_class,
                    str(enriched.emails).replace("'", '"'),
                    enriched.jd_text, enriched.jd_hash, enriched.dedupe_key,
                    enriched.subject_override, enriched.is_walk_in, job.id
                )
            )
            fetched += 1
            if fetched % 10 == 0:
                conn.commit()
                print(f"[{idx+1}/{len(rows)}] Fetched details for {fetched} jobs...")
            time.sleep(0.5)
        except Exception as e:
            print(f"Error fetching job {job.id} ({job.title}): {e}")

    conn.commit()
    conn.close()
    print(f"Done! Fetched: {fetched}, Skipped by pre-filter: {skipped}")

if __name__ == "__main__":
    main()
