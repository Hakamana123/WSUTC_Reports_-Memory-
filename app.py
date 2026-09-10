"""IA Mapping — Streamlit review tool.

STUB — last in the build order. No UI yet; this records the intended layout.

Sidebar:
  * band cut-point controls (low / mid / high), default (4, 6, 8)
  * "weight action by position" toggle (default on)
  * filters: program, assessment type, subject, confirmed-state
  * "re-score selected" button
  Changing a control recomputes derivations live.

Main:
  * one-time CSV upload (seeds the Google Sheet if empty)
  * editable table (st.data_editor), one row per task:
      subject # · position · type · weighting
      Assure band (editable)   — round-1 score shown as help text
      Inspire band (editable)  — round-1 score shown as help text
      Quadrant_R2 (derived)    — round-1 label shown beside, mismatch flagged
      axis-only action · suggested action (flagged when they differ, + reason)
      Action (editable) · Effort (editable; shown when not top tier)
      expander: QuickWins, ResourceReq, Rationale, round-1 note
  * rows needing a manual band are flagged "needs banding"
  * unsaved-changes indicator; Save (writes changed rows to the Sheet);
    per-row save; a separate Confirm control sets Confirmed_R2
  * Export button — CSV of the current view for circulation / re-import

All derivation goes through derivation.derive_task. All persistence goes
through store. This file is orchestration only.
"""

from __future__ import annotations

# TODO: implement the Streamlit UI
