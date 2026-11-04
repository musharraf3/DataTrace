"""Guards against publishing credentials. Runs in CI on every push."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSIGNMENT = re.compile(r"MODEL_API_KEY[ \t]*[=:][ \t]*['\"]?([A-Za-z0-9_\-\.]{12,})")


def _tracked():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [ROOT / line for line in out.splitlines() if line]


def test_no_tracked_file_assigns_an_api_key():
    leaks = []
    for path in _tracked():
        if path.suffix in {".wav", ".png", ".jpg"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if ASSIGNMENT.search(text):
            leaks.append(str(path.relative_to(ROOT)))
    assert not leaks, f"Possible credential in tracked files: {leaks}"


def test_env_files_are_ignored_and_untracked():
    tracked = {str(p.relative_to(ROOT)).replace("\\", "/") for p in _tracked()}
    assert ".env" not in tracked and ".streamlit/secrets.toml" not in tracked
    ignore = (ROOT / ".gitignore").read_text()
    assert ".env" in ignore and ".streamlit/secrets.toml" in ignore
