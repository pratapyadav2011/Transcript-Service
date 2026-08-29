from unittest.mock import MagicMock, patch

from app.services import mongo_writer
from app.tasks import hooks


@patch("app.services.mongo_writer.get_db")
def test_write_log_uses_dashboard_collection_and_schema(get_db):
    db = MagicMock()
    get_db.return_value = db

    mongo_writer.write_log(
        tag="MEETING_TRANSCRIPT_GENERATED",
        message="done",
        actor="Admin",
        meeting_id="meeting-1",
        status="succeeded",
        correlation_id="job-1",
    )

    document = db.application_logs.insert_one.call_args.args[0]
    assert document["applicationName"] == "Meetings"
    assert document["entityType"] == "meeting"
    assert document["entityId"] == "meeting-1"
    assert document["service"] == "transcript-service"
    assert document["status"] == "succeeded"
    assert document["correlationId"] == "job-1"
    assert document["expiresAt"] > document["time"]
    db.applicationlogs.insert_one.assert_not_called()


@patch("app.tasks.hooks.mongo_writer")
def test_success_writes_dashboard_completion_log(writer):
    hooks.on_success(
        "meeting-1",
        "transcript-1",
        "generated text",
        "Admin",
        source_label="https://example.com/video",
        job_id="job-1",
    )

    writer.update_transcript_text.assert_called_once_with(
        "transcript-1", "generated text",
    )
    writer.set_transcript_generated.assert_called_once_with("meeting-1")
    writer.write_log.assert_called_once_with(
        tag="MEETING_TRANSCRIPT_GENERATED",
        message="Meeting transcript generated successfully",
        actor="Admin",
        meeting_id="meeting-1",
        status="succeeded",
        correlation_id="job-1",
        details={
            "jobId": "job-1",
            "source": "https://example.com/video",
        },
    )


@patch("app.tasks.hooks.mongo_writer")
def test_failure_writes_visible_error_log(writer):
    hooks.on_failure("meeting-1", "Whisper failed", "Admin", job_id="job-1")

    writer.set_transcript_failed.assert_called_once_with("meeting-1", "Whisper failed")
    writer.write_log.assert_called_once_with(
        tag="MEETING_TRANSCRIPT_GENERATE_FAILED",
        message="Whisper failed",
        actor="Admin",
        meeting_id="meeting-1",
        log_type="error",
        status="failed",
        correlation_id="job-1",
        error={"message": "Whisper failed"},
        details={"jobId": "job-1"},
    )
