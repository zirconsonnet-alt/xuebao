from datetime import datetime
from pathlib import Path

from src.support.db import InternalDatabase


def test_codex_job_persistence(tmp_path: Path):
    db = InternalDatabase(db_path=tmp_path / "internal_api.db")
    try:
        db.create_codex_job(
            job_id="job12345",
            bot_self_id="10001",
            user_id=123456,
            group_id=None,
            chat_type="private",
            prompt="hello codex",
            status="queued",
            command_text="codex exec -",
            codex_session_id=None,
            resume_mode="new",
            source_message_id="7788",
        )

        job = db.get_codex_job("job12345")
        assert job is not None
        assert job["status"] == "queued"
        assert job["prompt"] == "hello codex"
        assert job["resume_mode"] == "new"

        started_at = datetime.now()
        finished_at = datetime.now()
        updated = db.update_codex_job_status(
            job_id="job12345",
            status="succeeded",
            result_text="done",
            codex_session_id="thread-001",
            resume_mode="fallback-new",
            started_at=started_at,
            finished_at=finished_at,
        )
        assert updated is True

        job = db.get_codex_job("job12345")
        assert job is not None
        assert job["status"] == "succeeded"
        assert job["result_text"] == "done"
        assert job["codex_session_id"] == "thread-001"
        assert job["resume_mode"] == "fallback-new"
        assert job["started_at"] is not None
        assert job["finished_at"] is not None

        latest_session = db.get_latest_codex_session(user_id=123456)
        assert latest_session == "thread-001"

        jobs = db.list_codex_jobs(user_id=123456, limit=5)
        assert len(jobs) == 1
        assert jobs[0]["job_id"] == "job12345"
    finally:
        db.close()
