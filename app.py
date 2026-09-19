"""Landing page. Select a tool from the sidebar.

(Working title — rename this app once you've settled on a name.)
"""

import streamlit as st

import auth

st.set_page_config(page_title="IA Mapping", page_icon="🧭", layout="wide")
auth.require_access()

st.title("IA Mapping")
st.markdown(
    """
Select a tool from the sidebar:

- **🧭 IA Mapping** — review assessment tasks on the Inspire × Assure axes,
  derive a quadrant and a sequence-aware redesign action, confirm and export.
- **📋 Workload Management** — teaching load in hours per staff member,
  against The College EA limits, with a dashboard for supervisors.

All changes save to one shared Google Sheet — see `SETUP_GOOGLE_SHEET.md` if
this is the first run.
"""
)
