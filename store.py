"""Google Sheet as the shared system of record.

STUB — built after loader.py. No logic yet; this file records the design.

Why a Google Sheet: the app runs on Streamlit Community Cloud, whose disk is
wiped on every redeploy/sleep, so saved state must live outside the app. One
Sheet, shared with a service account, is free, survives restarts, and is one
live copy the whole team sees. No WSU IT involved.

Auth: a GCP service account; its JSON key in st.secrets["gcp_service_account"].
The target Sheet is shared (editor) with that account's email.
Sheet id in st.secrets["sheet"]["id"].

Responsibilities:
  * seed(df)            — first run: write every cleaned row, Confirmed_R2 = FALSE
  * load()              — read the sheet into a DataFrame
  * save(changed_rows)  — write back only changed rows, stamp last_saved_by/at
  * merge_reupload(df)  — add new tasks + refresh base scores by RowKey,
                          never touching an override / note / Confirmed_R2

Stored columns = the input columns, plus:
  RowKey, AssureBand, InspireBand, Quadrant_R2, ActionSuggested, Action,
  Effort, QuickWins, ResourceReq, Rationale, Confirmed_R2,
  last_saved_by, last_saved_at
(the export's original Confirmed is carried through read-only as
 Confirmed_R1)

Concurrency: read-modify-write per save, last-write-wins, with a visible
"last saved by X at HH:MM" banner. Fine for a small review team.
"""

from __future__ import annotations

# TODO: implement seed(), load(), save(), merge_reupload()
