"""Print which Python packages the app will actually load. Run: .venv\\Scripts\\python.exe scripts\\doctor.py"""
import os
import sys

import altair
import pandas
import streamlit

print("python      ", sys.executable, sys.version.split()[0])
print("streamlit   ", streamlit.__version__, "from", os.path.dirname(streamlit.__file__))
print("pandas      ", pandas.__version__)
print("altair      ", altair.__version__)
print("PYTHONPATH  ", os.environ.get("PYTHONPATH", "(not set)"))
print("user site   ", "disabled" if os.environ.get("PYTHONNOUSERSITE") else "enabled")
ok = streamlit.__version__.startswith("1.66")
print("RESULT      ", "OK" if ok else "WRONG STREAMLIT: run  .venv\\Scripts\\python.exe -s run.py  (or set PYTHONNOUSERSITE=1)")
