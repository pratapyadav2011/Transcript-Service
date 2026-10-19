import os
import subprocess
import sys

OLD_NAMES = ("TRANSCRIPT_SECRET_KEY", "API_SECRET_KEY", "TOXICITY_SERVICE_TOKEN")


def _token(**env):
    """settings.API_SERVICE_TOKEN from a fresh interpreter (settings are fixed at import)."""
    clean = {k: v for k, v in os.environ.items() if k != "API_SERVICE_TOKEN" and k not in OLD_NAMES}
    clean.update(env)
    # Run from an empty dir so load_dotenv() can't pick up a real .env.
    code = (
        "import sys; sys.path.insert(0, %r)\n"
        "from app.core.config import settings\n"
        "print(settings.API_SERVICE_TOKEN)"
    ) % os.getcwd()
    return subprocess.run(
        [sys.executable, "-c", code], env=clean, cwd="/tmp",
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def test_reads_api_service_token():
    assert _token(API_SERVICE_TOKEN="one") == "one"


def test_old_names_are_ignored():
    assert _token(**{name: "old" for name in OLD_NAMES}) == ""
