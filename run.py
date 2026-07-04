"""run.py — Launch the Streamlit app with the correct Python path.

Usage: python run.py
"""

import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Launch Streamlit programmatically
from streamlit.web import cli as stcli

sys.argv = ["streamlit", "run", "ui/app.py"]
stcli.main()
