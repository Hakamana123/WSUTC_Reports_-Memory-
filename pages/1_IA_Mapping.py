"""IA Mapping — review page.

Upload the SharePoint export once to seed the shared Google Sheet, then
review: bands, quadrant, sequence-aware action all derive live from the
sidebar controls. Editing a row and hitting Save freezes that row's current
bands/action as its working value (it stops following the sliders); an
untouched row keeps tracking the sidebar cut-points and toggle.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth
import config
import derivation
import loader
import store

st.set_page_config(page_title="IA Mapping", page_icon="🧭", layout="wide")
auth.require_access()
st.title("🧭 IA Mapping")
st.caption(
    "Inspire × Assure review — based on Koh & Roffey, "
    "*Assessment-Mapping Tool: Proposed Relabelling on Inspire × Assure Axes* (Sep 2026)."
)

EDITABLE_COLS = [
    "AssureBand", "InspireBand", "Action", "Effort",
    "QuickWins", "ResourceReq", "Rationale", "Confirmed_R2",
    "Weighting_n", "InspireScore_n", "AssureScore_n",
]


# --------------------------------------------------------------------------
# connection
# --------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def _backend():
    return store.backend_from_secrets(st.secrets)


def _reload():
    st.session_state["ia_stored"] = store.load(_backend())


try:
    _backend()
except Exception as exc:  # noqa: BLE001
    st.error(
        "Can't connect to the Google Sheet. Check `.streamlit/secrets.toml` "
        f"against SETUP_GOOGLE_SHEET.md.\n\n`{exc}`"
    )
    st.stop()

if "ia_stored" not in st.session_state:
    with st.spinner("Loading from the Sheet…"):
        _reload()

stored: pd.DataFrame = st.session_state["ia_stored"]
# recompute the numeric working copies fresh every render, from the actual
# stored strings — never trust a stale helper column from a previous edit
stored["InspireScore_n"] = pd.to_numeric(stored["Inspire Score"], errors="coerce")
stored["AssureScore_n"] = pd.to_numeric(stored["Assure Score"], errors="coerce")
stored["Weighting_n"] = pd.to_numeric(stored["Weighting"], errors="coerce")


# --------------------------------------------------------------------------
# seed / re-import
# --------------------------------------------------------------------------


def _do_import(file, mode: str) -> None:
    result = loader.read_export(file.getvalue())
    if result.warnings:
        with st.expander(f"⚠ {len(result.warnings)} note(s) from cleaning the export", expanded=False):
            for w in result.warnings:
                st.write(f"- {w}")
    if mode == "seed":
        store.seed(_backend(), result.df)
        st.success(f"Seeded {len(result.df)} tasks.")
    else:
        _, summary = store.merge_reupload(_backend(), result.df)
        st.success(
            f"Added {len(summary['added'])} new task(s), "
            f"refreshed {len(summary['refreshed'])}, "
            f"{len(summary['in_sheet_not_in_reupload'])} in the Sheet weren't in this export."
        )
    _reload()
    st.rerun()


if stored.empty:
    st.info("The Sheet is empty. Upload the SharePoint export to seed it.")
    up = st.file_uploader("Assessment-mapping export (.csv)", type="csv", key="seed_upload")
    if up and st.button("Seed the Sheet", type="primary"):
        _do_import(up, "seed")
    st.stop()

with st.expander("Import a new export (adds new tasks, refreshes scores — never touches your reviews)"):
    up2 = st.file_uploader("Assessment-mapping export (.csv)", type="csv", key="reup_upload")
    if up2 and st.button("Merge this export into the Sheet"):
        _do_import(up2, "merge")


# --------------------------------------------------------------------------
# sidebar controls
# --------------------------------------------------------------------------

# Band cut points and the position toggle are USED here but RENDERED at the
# bottom of the sidebar (see below) - read whatever the widgets last set via
# session_state (falls back to the config defaults on the very first run).
low = st.session_state.get("cut_low", config.DEFAULT_CUT_POINTS[0])
mid = st.session_state.get("cut_mid", config.DEFAULT_CUT_POINTS[1])
high = st.session_state.get("cut_high", config.DEFAULT_CUT_POINTS[2])
if not (low <= mid <= high):
    cut_points = config.DEFAULT_CUT_POINTS
else:
    cut_points = (low, mid, high)
weight_by_position = st.session_state.get(
    "weight_by_position", config.WEIGHT_BY_POSITION_DEFAULT
)

def _split_codes(value: str) -> list[str]:
    return [c.strip() for c in str(value).split(",") if c.strip()]


st.sidebar.subheader("Filters")
all_program_codes = sorted(
    {code for codes in stored["Program Code"] for code in _split_codes(codes)}
)
programs = st.sidebar.multiselect("Program", all_program_codes)
types = st.sidebar.multiselect(
    "Assessment type", sorted(stored["Assessment Type"].unique())
)
subject_q = st.sidebar.text_input("Subject code / title contains")
confirmed_filter = st.sidebar.selectbox(
    "Confirmation", ["All", "Not yet confirmed", "Confirmed"]
)
attention_only = st.sidebar.checkbox("Only rows flagged for attention")

st.sidebar.divider()
reviewer = st.sidebar.text_input("Your name (required to save)")

if st.sidebar.button("↻ Reload from Sheet"):
    _reload()
    st.rerun()


# --------------------------------------------------------------------------
# live derivation
# --------------------------------------------------------------------------


def _num_or_none(v):
    return None if pd.isna(v) else int(v)


def _fmt_num(v) -> str:
    """Store a whole number cleanly ("6" not "6.0"); keep a fraction if there is one."""
    if pd.isna(v):
        return ""
    return str(int(v)) if float(v).is_integer() else str(v)


def _derive_row(row: pd.Series) -> derivation.Derivation:
    return derivation.derive_task(
        assure_score=None if pd.isna(row["AssureScore_n"]) else float(row["AssureScore_n"]),
        inspire_score=None if pd.isna(row["InspireScore_n"]) else float(row["InspireScore_n"]),
        assure_band_override=row["AssureBand"] or None,
        inspire_band_override=row["InspireBand"] or None,
        assessment_number=_num_or_none(row["AssessmentNumber_n"]),
        subject_max_number=_num_or_none(row["SubjectMaxNumber"]),
        confirmed=row["Confirmed_R2"] == "TRUE",
        rescore=False,
        weight_by_position=weight_by_position,
        cut_points=cut_points,
    )


def _flags(row: pd.Series, d: derivation.Derivation) -> str:
    bits = []
    if d.needs_manual:
        bits.append("⚠ needs banding (no round-1 score)")
    elif d.quadrant and row["Quadrant_R1"]:
        r1 = row["Quadrant_R1"]
        matches = (
            (r1 == "Inspire & Assure" and d.quadrant == "High Inspire · High Assure")
            or (r1 == "Inspire" and d.quadrant == "High Inspire · Low Assure")
            or (r1 == "Assure" and d.quadrant == "Low Inspire · High Assure")
            or (r1 == "Low value" and d.quadrant == "Low Inspire · Low Assure")
        )
        if not matches:
            bits.append(f"quadrant ≠ round-1 ({r1})")
    if d.position_changed_action:
        bits.append(f"↕ {d.action_reason}")
    return " · ".join(bits)


derived = stored.apply(_derive_row, axis=1)
view = stored.copy()
view["Position"] = [d.position for d in derived]
view["Quadrant"] = [d.quadrant or "—" for d in derived]
view["AxisOnlyAction"] = [d.action_axis_only or "—" for d in derived]
view["SuggestedAction"] = [d.action_suggested or "—" for d in derived]
view["Flags"] = [_flags(r, d) for r, d in zip(stored.to_dict("records"), derived)]

# pre-fill the editable columns with the resolved working value (override if
# set, else the live default) so the editor shows what's actually in play
view["AssureBand"] = [d.assure_band or "" for d in derived]
view["InspireBand"] = [d.inspire_band or "" for d in derived]
view["Action"] = [a or s for a, s in zip(stored["Action"], view["SuggestedAction"])]

view.index = stored["RowKey"]


# --------------------------------------------------------------------------
# filters
# --------------------------------------------------------------------------


mask = pd.Series(True, index=view.index)
if programs:
    selected_programs = set(programs)
    mask &= stored.set_axis(view.index)["Program Code"].apply(
        lambda codes: bool(selected_programs & set(_split_codes(codes)))
    )
if types:
    mask &= stored.set_axis(view.index)["Assessment Type"].isin(types)
if subject_q:
    hay = (
        stored.set_axis(view.index)["Subject Code"] + " "
        + stored.set_axis(view.index)["Subject Title"]
    )
    mask &= hay.str.contains(subject_q, case=False, na=False)
if confirmed_filter == "Confirmed":
    mask &= view["Confirmed_R2"] == "TRUE"
elif confirmed_filter == "Not yet confirmed":
    mask &= view["Confirmed_R2"] != "TRUE"
if attention_only:
    mask &= view["Flags"] != ""

visible = view[mask]
st.caption(f"Showing {len(visible)} of {len(view)} tasks.")


# --------------------------------------------------------------------------
# the table
# --------------------------------------------------------------------------


display_cols = [
    "Subject Code", "Subject Title", "Assessment Number", "Position",
    "Assessment Type", "Weighting_n", "InspireScore_n", "AssureScore_n",
    "AssureBand", "InspireBand", "Quadrant", "Quadrant_R1",
    "AxisOnlyAction", "SuggestedAction", "Action", "Effort",
    "QuickWins", "ResourceReq", "Rationale", "Notes/Comments",
    "Confirmed_R2", "Confirmed_R1", "Flags",
]

column_config = {
    "Subject Code": st.column_config.TextColumn("Subject", disabled=True),
    "Subject Title": st.column_config.TextColumn("Title", disabled=True, width="medium"),
    "Assessment Number": st.column_config.TextColumn("#", disabled=True, width="small"),
    "Position": st.column_config.TextColumn("Pos.", disabled=True, width="small"),
    "Assessment Type": st.column_config.TextColumn("Type", disabled=True),
    "Weighting_n": st.column_config.NumberColumn(
        "Wt%", min_value=0, max_value=100, step=1, width="small",
        help="Editing this corrects the round-1 export value.",
    ),
    "InspireScore_n": st.column_config.NumberColumn(
        "Insp. R1", min_value=1, max_value=10, step=1, width="small",
        help="Editing this corrects the round-1 export value — bands recompute from it.",
    ),
    "AssureScore_n": st.column_config.NumberColumn(
        "Assure R1", min_value=1, max_value=10, step=1, width="small",
        help="Editing this corrects the round-1 export value — bands recompute from it.",
    ),
    "AssureBand": st.column_config.SelectboxColumn("Assure band", options=config.ASSURE_BANDS, required=True),
    "InspireBand": st.column_config.SelectboxColumn("Inspire band", options=config.INSPIRE_BANDS, required=True),
    "Quadrant": st.column_config.TextColumn("Quadrant", disabled=True, width="medium"),
    "Quadrant_R1": st.column_config.TextColumn("R1 label", disabled=True),
    "AxisOnlyAction": st.column_config.TextColumn("Axis-only", disabled=True),
    "SuggestedAction": st.column_config.TextColumn("Suggested", disabled=True),
    "Action": st.column_config.SelectboxColumn("Action", options=config.ACTIONS, required=True),
    "Effort": st.column_config.SelectboxColumn("Effort", options=[""] + config.EFFORT_LEVELS),
    "QuickWins": st.column_config.TextColumn("Quick wins"),
    "ResourceReq": st.column_config.TextColumn("Resource reqs"),
    "Rationale": st.column_config.TextColumn("Rationale"),
    "Notes/Comments": st.column_config.TextColumn("R1 note", disabled=True, width="medium"),
    "Confirmed_R2": st.column_config.CheckboxColumn("Confirmed"),
    "Confirmed_R1": st.column_config.TextColumn("R1 ✓", disabled=True, width="small"),
    "Flags": st.column_config.TextColumn("Flags", disabled=True, width="medium"),
}

edited = st.data_editor(
    visible[display_cols],
    column_config=column_config,
    hide_index=True,
    num_rows="fixed",
    use_container_width=True,
    key="ia_editor",
)
edited.index = visible.index

# merge any edits straight back into the stored frame, every rerun, so a
# filter change right after an edit can never lose it
changed_mask = (edited[EDITABLE_COLS] != visible[EDITABLE_COLS]).any(axis=1)
changed_keys = edited.index[changed_mask].tolist()

if changed_keys:
    working = stored.set_index("RowKey", drop=False)
    for key in changed_keys:
        row = edited.loc[key]
        working.loc[key, "AssureBand"] = row["AssureBand"]
        working.loc[key, "InspireBand"] = row["InspireBand"]
        working.loc[key, "Action"] = row["Action"]
        working.loc[key, "Effort"] = row["Effort"]
        working.loc[key, "QuickWins"] = row["QuickWins"]
        working.loc[key, "ResourceReq"] = row["ResourceReq"]
        working.loc[key, "Rationale"] = row["Rationale"]
        working.loc[key, "Confirmed_R2"] = "TRUE" if row["Confirmed_R2"] else "FALSE"
        working.loc[key, "Weighting"] = _fmt_num(row["Weighting_n"])
        working.loc[key, "Inspire Score"] = _fmt_num(row["InspireScore_n"])
        working.loc[key, "Assure Score"] = _fmt_num(row["AssureScore_n"])
        # freeze the quadrant implied by the bands just written
        working.loc[key, "Quadrant_R2"] = derivation.quadrant(
            derivation.inspire_ordinal(row["InspireBand"]),
            derivation.assure_ordinal(row["AssureBand"]),
        )
    st.session_state["ia_stored"] = working.reset_index(drop=True)
    stored = st.session_state["ia_stored"]

pending = st.session_state.get("ia_pending_keys", set())
pending |= set(changed_keys)
st.session_state["ia_pending_keys"] = pending


# --------------------------------------------------------------------------
# reset-to-round-1 (replaces "re-score" now there's no LLM)
# --------------------------------------------------------------------------


with st.sidebar.expander("Reset rows to round-1 default"):
    resettable = stored[stored["Confirmed_R2"] != "TRUE"]
    labels = {
        k: f"{s} A{n}" for k, s, n in zip(
            resettable["RowKey"], resettable["Subject Code"], resettable["Assessment Number"]
        )
    }
    picked = st.multiselect("Rows", options=list(labels), format_func=lambda k: labels[k])
    if picked and st.button("Reset selected to live score"):
        working = stored.set_index("RowKey", drop=False)
        for key in picked:
            working.loc[key, ["AssureBand", "InspireBand", "Action", "Quadrant_R2"]] = ""
        st.session_state["ia_stored"] = working.reset_index(drop=True)
        st.session_state["ia_pending_keys"] = pending | set(picked)
        st.rerun()

st.sidebar.divider()
st.sidebar.subheader("Band cut points")
st.sidebar.caption("A round-1 score bands as: ≥high → top band, ≥mid, ≥low, else bottom.")
st.sidebar.number_input("low", 1, 10, config.DEFAULT_CUT_POINTS[0], key="cut_low")
st.sidebar.number_input("mid", 1, 10, config.DEFAULT_CUT_POINTS[1], key="cut_mid")
st.sidebar.number_input("high", 1, 10, config.DEFAULT_CUT_POINTS[2], key="cut_high")
if not (st.session_state["cut_low"] <= st.session_state["cut_mid"] <= st.session_state["cut_high"]):
    st.sidebar.error("cut points must be low ≤ mid ≤ high — using the default for now")
st.sidebar.toggle(
    "Weight action by sequence position",
    value=config.WEIGHT_BY_POSITION_DEFAULT,
    key="weight_by_position",
    help="Softens a weak Assure on an early task or a weak Inspire on a final "
    "task. Not part of the endorsed proposal — an extension.",
)


# --------------------------------------------------------------------------
# save / export
# --------------------------------------------------------------------------


n_pending = len(st.session_state.get("ia_pending_keys", set()))
col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    if n_pending:
        st.warning(f"{n_pending} row(s) changed, not yet saved.")
    else:
        st.success("Everything's saved.")
with col2:
    save_clicked = st.button(
        "💾 Save changes", type="primary",
        disabled=not (n_pending and reviewer),
        help="Enter your name in the sidebar first" if not reviewer else None,
    )
with col3:
    st.download_button(
        "⬇ Export CSV",
        data=loader.to_export_csv(stored),
        file_name="ia_mapping_export.csv",
        mime="text/csv",
    )

if save_clicked:
    keys = list(st.session_state["ia_pending_keys"])
    result = store.save(_backend(), stored, changed_keys=keys, reviewer=reviewer)
    st.session_state["ia_stored"] = result
    st.session_state["ia_pending_keys"] = set()
    st.success(f"Saved {len(keys)} row(s).")
    st.rerun()
