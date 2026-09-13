"""Workload Management — placeholder.

Not yet scoped. Waiting on Josiah for: what it tracks, whose workload, what
data it reads from, and whether it shares the same Google Sheet or needs its
own store.
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auth

st.set_page_config(page_title="Workload Management", page_icon="📋", layout="wide")
auth.require_access()
st.title("📋 Workload Management")
st.info("Not built yet — waiting on the spec for what this page should do.")
