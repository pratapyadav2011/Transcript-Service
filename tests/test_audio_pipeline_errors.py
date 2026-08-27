from app.services.downloader.audio_pipeline import (
    MANUAL_DOWNLOAD_MESSAGE,
    _final_acquisition_error,
)


def test_403_failure_explains_manual_browser_download():
    result = _final_acquisition_error(
        "https://example.com/player/1",
        ["Direct download failed: 403 Client Error: Forbidden"],
    )

    assert result == MANUAL_DOWNLOAD_MESSAGE
    assert "Find Download Links" in result
    assert "Upload File" in result


def test_non_403_failure_keeps_strategy_details():
    result = _final_acquisition_error(
        "https://example.com/player/1",
        ["ffmpeg exited with code 8"],
    )

    assert result.startswith("All audio acquisition strategies failed.")
    assert "ffmpeg exited with code 8" in result
