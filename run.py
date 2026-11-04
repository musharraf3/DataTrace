"""Launch from the repository even before an editable install."""
import os
from pathlib import Path
import runpy
import sys

if __name__ == "__main__":
    project = Path(__file__).resolve().parent
    os.chdir(project)
    sys.path.insert(0, str(project / "src"))
    sys.argv = ["streamlit", "run", str(project / "app.py")] + sys.argv[1:]
    runpy.run_module("streamlit", run_name="__main__")
