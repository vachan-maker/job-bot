import tempfile
from pathlib import Path
from email import message_from_bytes
from jobbot.models import Job, Draft
from jobbot.mailer import render_draft, create_mime_message, send_draft
from jobbot.rank import load_config

def test_mailer_draft_and_mime():
    config = load_config()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        dummy_pdf = tmp_path / "resume.pdf"
        dummy_pdf.write_bytes(b"%PDF-1.4 dummy pdf bytes")

        job = Job(
            id=123,
            source="infopark",
            source_job_id="555",
            url="https://infopark.in/job/555",
            company="Acme Corp",
            title="Laravel Developer",
            emails=["hr@acme.com"],
            role_family="php_laravel"
        )

        candidate_name = config.get("candidate", {}).get("name", "Applicant")
        candidate_email = config.get("candidate", {}).get("email", "applicant@example.com")
        draft = render_draft(job, dummy_pdf, config)
        assert draft.to_addr == "hr@acme.com"
        assert "Laravel Developer" in draft.subject
        assert candidate_name in draft.body_text
        assert "LogicLabz" in draft.body_text

        msg = create_mime_message(draft, config)
        assert msg["To"] == "hr@acme.com"
        assert msg["Bcc"] == candidate_email
        assert msg["Reply-To"] == candidate_email
        assert msg["Message-ID"]

        # Check attachment
        attachments = list(msg.iter_attachments())
        assert len(attachments) == 1
        assert attachments[0].get_filename() == "resume.pdf"

        # Test dry-run send
        preview_dir = tmp_path / "preview"
        res = send_draft(draft, config, dry_run=True, preview_dir=preview_dir)
        assert res.status == "dry_run"
        eml_files = list(preview_dir.glob("*.eml"))
        assert len(eml_files) == 1
