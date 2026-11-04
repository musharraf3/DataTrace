"""Streamlit entry point. Run: python -m streamlit run app.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from datatrace.ui import main  # noqa: E402

main()
