"""A shared-password gate.

Streamlit Community Cloud's free tier only offers *public* apps — anyone with
the URL can open it, no Streamlit-managed login. This is a lightweight stand-
in until/unless something stronger (e.g. `st.login` with Google/Microsoft
OIDC) is worth the extra setup: one shared password, checked once per browser
session, kept in `st.secrets` like every other credential here.

Call `require_access()` as the first Streamlit call on every page.
"""

from __future__ import annotations

import streamlit as st


def require_access() -> None:
    if st.session_state.get("_authed"):
        return

    st.title("🔒 IA Mapping")
    pw = st.text_input("Access password", type="password")
    if st.button("Enter") or pw:
        expected = st.secrets.get("app", {}).get("access_password")
        if not expected:
            st.error("No access_password set in secrets — see SETUP_GOOGLE_SHEET.md.")
            st.stop()
        if pw == expected:
            st.session_state["_authed"] = True
            st.rerun()
        elif pw:
            st.error("Wrong password.")
    st.stop()
