"""Workload Management — each person's year in hours, for supervisors.

Supervisors keep four lists: the staff they manage, the teaching each person
has (one line per class, with its session, block and discipline), higher
duties and other duties, and the Calendar of blocks and teaching weeks. The
dashboard adds it all up per person across every discipline and session into
a year — to date, left and projected — against the annual target for their
role (16 DI hrs/wk × 36 weeks = 576 h for a full-time Teacher, pro rata).

Everything saves to the shared Google Sheet; every change is also appended to
a log tab, shown under History.
"""

from __future__ import annotations

import datetime as dt
import importlib
import sys
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import auth
import store
import workload_config as cfg
import workload_rules as rules
import workload_store as wstore

# Streamlit Cloud pulls a new commit without restarting Python: this page is
# re-read from disk every run, but helper modules imported before the pull
# (store.py, via IA Mapping) stay as the old code until the app is rebooted.
# Reload them, in dependency order, so a push always takes effect here.
for _m in (store, cfg, rules, wstore):
    importlib.reload(_m)

from workload_store import ADJUSTMENTS, ALLOCATIONS, CALENDAR, STAFF  # noqa: E402

st.set_page_config(page_title="Workload Management", page_icon="📋", layout="wide")
auth.require_access()
st.title("📋 Workload Management")
_limits = " · ".join(
    f"{r} {v:g}"
    for r, v in cfg.ROLES.items() if v is not None
)
st.caption(
    "Each person's year in hours — teaching plus higher duties and other duties — against "
    f"an annual target of their role's Direct Instruction hrs/wk × {cfg.ANNUAL_WEEKS:g} weeks "
    f"(The College Enterprise Agreement 2022): {_limits} hrs/wk, pro rata by FTE. "
    f"A full-time Teacher's year is {cfg.ROLES[cfg.DEFAULT_ROLE] * cfg.ANNUAL_WEEKS:g} h. "
    "Casual teachers have no target."
)

NUMERIC = {"FTE", "Classes", "DI hrs/wk", "DI relief hrs/wk", "Weeks", "Teaching weeks"}
BOOL = {"Active"}
DATE = {"Start date"}


# --------------------------------------------------------------------------
# connection + session state
# --------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def _cached_backends(tables: tuple[str, ...]):  # noqa: ARG001 — cache key only
    return wstore.backends_from_secrets(st.secrets)


def _backends():
    # keyed on the table names, so an update that adds a tab gets a fresh set
    # instead of the one cached by the old code
    return _cached_backends(tuple(wstore.TABLES))


def _reload():
    b = _backends()
    st.session_state["wl_data"] = {t.name: wstore.load(b[t.name], t) for t in wstore.TABLES.values()}
    st.session_state["wl_pending"] = {t: {"changed": set(), "removed": set()} for t in wstore.TABLES}
    _bump()


def _bump():
    st.session_state["wl_ver"] = st.session_state.get("wl_ver", 0) + 1


try:
    _backends()
except Exception as exc:  # noqa: BLE001
    st.error(
        "Can't connect to the Google Sheet. Check `.streamlit/secrets.toml` "
        f"against SETUP_GOOGLE_SHEET.md.\n\n`{exc}`"
    )
    st.stop()

# (also after an update adds a table, for sessions opened before it)
if "wl_data" not in st.session_state or set(wstore.TABLES) - set(st.session_state["wl_data"]):
    with st.spinner("Loading from the Sheet…"):
        _reload()

data: dict[str, pd.DataFrame] = st.session_state["wl_data"]
pending: dict[str, dict[str, set]] = st.session_state["wl_pending"]
staff_df, alloc_df, adj_df = data[STAFF.name], data[ALLOCATIONS.name], data[ADJUSTMENTS.name]
cal_df = data[CALENDAR.name]


def _fmt(v) -> str:
    """A cell as the string the Sheet stores. Handles numpy scalars too — the
    editor hands back np.bool_ / np.int64 in some rows and Python types in
    others, and both must format identically or every row looks edited."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "TRUE" if v else "FALSE"
    if isinstance(v, dt.date):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, (int, float, np.integer, np.floating)):
        return str(int(v)) if float(v).is_integer() else str(round(float(v), 2))
    return str(v)


def _add_rows(table, rows: list[dict]) -> None:
    if not rows:
        return
    df = data[table.name]
    data[table.name] = pd.concat([df, pd.DataFrame(rows).reindex(columns=df.columns, fill_value="")],
                                 ignore_index=True)
    pending[table.name]["changed"].update(r["ID"] for r in rows)
    _bump()


# --------------------------------------------------------------------------
# sidebar
# --------------------------------------------------------------------------


this_year = pd.Timestamp.today().year
default_session = rules.default_session()
years = sorted(
    {str(s).partition(" ")[0] for t in (alloc_df, adj_df, cal_df) for s in t["Session"] if s}
    | {f"{y % 100:02d}" for y in (this_year - 1, this_year, this_year + 1)}
)

st.sidebar.subheader("View")
default_yy = default_session.partition(" ")[0]
yy = st.sidebar.selectbox("Year", years, index=years.index(default_yy) if default_yy in years else 0,
                          format_func=lambda y: f"20{y}")
year_sessions = rules.year_sessions(yy)
new_row_session = default_session if default_session in year_sessions else year_sessions[0]
as_at = pd.Timestamp(st.sidebar.date_input(
    "As at", dt.date.today(), format="DD/MM/YYYY",
    help="Hours to date count the teaching weeks up to and including this day.",
))
supervisors = sorted({s for s in staff_df["Supervisor"] if s})
sup_filter = st.sidebar.multiselect("Supervisor", supervisors, help="Show the staff you supervise.")
disciplines = sorted(set(cfg.DISCIPLINES) | {d for d in alloc_df["Discipline"] if d}
                     | {d for d in staff_df["Home discipline"] if d})
disc_filter = st.sidebar.multiselect(
    "Discipline", disciplines,
    help="Show anyone teaching in these disciplines this year — with their "
    "whole load, including hours in other disciplines.",
)

st.sidebar.divider()
by = st.sidebar.text_input("Your name (required to save)")
if st.sidebar.button("↻ Reload from Sheet"):
    _reload()
    st.rerun()

# who's in view
in_view = set(staff_df.loc[staff_df["Active"].str.upper() != "FALSE", "Staff"])
if sup_filter:
    in_view &= set(staff_df.loc[staff_df["Supervisor"].isin(sup_filter), "Staff"])
if disc_filter:
    in_view &= set(alloc_df.loc[alloc_df["Session"].isin(year_sessions)
                                & alloc_df["Discipline"].isin(disc_filter), "Staff"])


# --------------------------------------------------------------------------
# save bar (top, so it's visible from every tab)
# --------------------------------------------------------------------------


n_changed = sum(len(p["changed"]) for p in pending.values())
n_removed = sum(len(p["removed"]) for p in pending.values())
bar1, bar2 = st.columns([4, 1])
with bar1:
    if n_changed or n_removed:
        st.warning(
            f"{n_changed} row(s) changed" + (f", {n_removed} removed" if n_removed else "")
            + " — not yet saved." + ("" if by else " Enter your name in the sidebar to save.")
        )
with bar2:
    if st.button("💾 Save changes", type="primary", disabled=not ((n_changed or n_removed) and by),
                 use_container_width=True):
        b = _backends()
        for t in wstore.TABLES.values():
            p = pending[t.name]
            if p["changed"] or p["removed"]:
                data[t.name] = wstore.save(b[t.name], b[wstore.LOG_NAME], t, data[t.name],
                                           p["changed"], p["removed"], by)
        st.session_state["wl_pending"] = {t: {"changed": set(), "removed": set()} for t in wstore.TABLES}
        _bump()
        st.toast(f"Saved {n_changed + n_removed} change(s).")
        st.rerun()


# --------------------------------------------------------------------------
# generic editable table
# --------------------------------------------------------------------------


def edit_table(table, visible: pd.DataFrame, column_config: dict, order: list[str],
               defaults: dict, key: str) -> None:
    """A dynamic-rows editor over `visible` (a slice of the table). Changes,
    new rows and deleted rows are merged straight back into the session copy
    and queued for saving."""
    view = visible.copy()
    for c in order:
        if c in NUMERIC:
            view[c] = pd.to_numeric(view[c], errors="coerce")
        elif c in BOOL:
            view[c] = view[c].str.upper() != "FALSE"
        elif c in DATE:
            view[c] = pd.to_datetime(view[c], errors="coerce").dt.date
    view = view[["ID"] + order].reset_index(drop=True)

    edited = st.data_editor(
        view,
        column_config={"ID": None, **column_config},
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=f"{key}_{st.session_state['wl_ver']}",
    )

    df = data[table.name].set_index("ID", drop=False)
    before = view.set_index("ID", drop=False)
    changed, removed = set(), set()
    renames: dict[str, str] = {}

    kept_ids = {i for i in edited["ID"] if isinstance(i, str) and i}
    for rid in before.index:
        if rid not in kept_ids:
            removed.add(rid)

    for _, row in edited.iterrows():
        rid = row["ID"] if isinstance(row["ID"], str) and row["ID"] else None
        values = {c: _fmt(row[c]) for c in order}
        if rid is None:
            rid = wstore.new_id()
            values = {**{c: _fmt(v) for c, v in defaults.items()},
                      **{c: v for c, v in values.items() if v != ""}}
            df.loc[rid] = pd.Series({"ID": rid, **values}).reindex(df.columns, fill_value="")
            changed.add(rid)
            continue
        old = {c: _fmt(before.loc[rid, c]) for c in order}
        if values != old:
            if table is STAFF and values["Staff"] != old["Staff"] and old["Staff"]:
                renames[old["Staff"]] = values["Staff"]
            for c, v in values.items():
                df.loc[rid, c] = v
            changed.add(rid)

    if not (changed or removed):
        return
    data[table.name] = df.drop(index=list(removed)).reset_index(drop=True)
    pending[table.name]["changed"] |= changed
    pending[table.name]["changed"] -= removed
    pending[table.name]["removed"] |= removed

    # a renamed staff member keeps their teaching and duties
    for old_name, new_name in renames.items():
        for t in (ALLOCATIONS, ADJUSTMENTS):
            tdf = data[t.name]
            hit = tdf["Staff"] == old_name
            if hit.any():
                tdf.loc[hit, "Staff"] = new_name
                pending[t.name]["changed"] |= set(tdf.loc[hit, "ID"])
    _bump()
    st.rerun()


staff_names = sorted(n for n in staff_df["Staff"] if n)


# --------------------------------------------------------------------------
# tabs
# --------------------------------------------------------------------------


tab_dash, tab_teach, tab_adj, tab_cal, tab_staff, tab_hist = st.tabs(
    ["📊 Dashboard", "📚 Teaching", "⬆ Higher duties & other duties", "📅 Calendar", "👥 Staff",
     "🗂 History"]
)

# discipline colours, with HDA / other duties always the same grey
_PALETTE = ["#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b", "#eeca3b", "#b279a2",
            "#ff9da6", "#9d755d"]
_DUTIES_COLOUR = "#9e9e9e"


# ---------------------------------------------------------------- dashboard
with tab_dash:
    summary = rules.summarise_year(staff_df, alloc_df, adj_df, cal_df, yy, as_at)
    if not summary.empty:
        summary = summary[summary["Staff"].isin(in_view)]
    blocks = rules.calendar_blocks(cal_df, yy)
    cal_weeks = sum(b["weeks"] for b in blocks)

    if staff_df.empty:
        st.info("Start on the 👥 Staff tab — add the people you supervise, then the year's "
                "blocks on 📅 Calendar, then their teaching on 📚 Teaching.")
    elif summary.empty:
        st.info("Nobody matches the filters in the sidebar.")
    else:
        if not blocks:
            st.warning(f"No blocks in the 📅 Calendar for 20{yy} yet — every hour counts as zero "
                       "until the blocks and their teaching weeks are entered.")

        n = summary["Status"].value_counts()
        m = st.columns(6)
        m[0].metric("Staff", len(summary))
        m[1].metric(rules.STATUS_ON, int(n.get(rules.STATUS_ON, 0)),
                    help=f"Projected year within ±{cfg.ON_TRACK_TOLERANCE:.0%} of the target.")
        m[2].metric(rules.STATUS_OVER, int(n.get(rules.STATUS_OVER, 0)))
        m[3].metric(rules.STATUS_UNDER, int(n.get(rules.STATUS_UNDER, 0)))
        m[4].metric(f"{rules.DUTIES} (h)", f"{summary['Duties'].sum():,.0f}",
                    help="Higher duties and other duties across everyone shown, for the year.")
        m[5].metric("Across 2+ disciplines", int((summary["by_discipline"].apply(len) > 1).sum()))

        status_filter = st.multiselect(
            "Show", rules.STATUSES, placeholder="Everyone — or pick a status",
            help="Filter the chart and table by colour.",
        )
        shown = summary[summary["Status"].isin(status_filter)] if status_filter else summary

        # the year per person: teaching by discipline, then HDA / other duties
        long = [
            {"Staff": r["Staff"], "Part": d, "Hours": h}
            for _, r in shown.iterrows() for d, h in r["by_discipline"].items()
        ] + [
            {"Staff": r["Staff"], "Part": rules.DUTIES, "Hours": r["Duties"]}
            for _, r in shown.iterrows() if r["Duties"]
        ]
        if long:
            parts = sorted({x["Part"] for x in long} - {rules.DUTIES})
            colours = [_PALETTE[i % len(_PALETTE)] for i in range(len(parts))]
            y = alt.Y("Staff:N", sort=list(shown.sort_values("Total", ascending=False)["Staff"]),
                      title=None)
            bars = alt.Chart(pd.DataFrame(long)).mark_bar().encode(
                y=y,
                x=alt.X("sum(Hours):Q", title=f"Hours in 20{yy} (projected)"),
                color=alt.Color("Part:N", title=None,
                                scale=alt.Scale(domain=parts + [rules.DUTIES], range=colours + [_DUTIES_COLOUR]),
                                legend=alt.Legend(orient="bottom")),
                order=alt.Order("Part:N"),
                tooltip=["Staff", alt.Tooltip("Part:N", title="Discipline / duties"),
                         alt.Tooltip("sum(Hours):Q", title="Hours", format=",.0f")],
            )
            targets = shown[shown["Target"].notna()][["Staff", "Target", "To date"]]
            target_tick = alt.Chart(targets).mark_tick(color="black", thickness=2, size=18).encode(
                y=y, x="Target:Q", tooltip=[alt.Tooltip("Target:Q", format=",.0f")])
            done_tick = alt.Chart(shown[["Staff", "To date"]]).mark_point(
                shape="triangle-down", filled=True, color="black", size=60, yOffset=-10,
            ).encode(y=y, x="To date:Q", tooltip=[alt.Tooltip("To date:Q", format=",.0f")])
            chart = alt.layer(bars, target_tick, done_tick).properties(height=alt.Step(30))
            st.altair_chart(chart, use_container_width=True)
            st.caption(
                "Bars: each person's projected year — teaching by discipline, then "
                f"{rules.DUTIES} in grey. Black tick: annual target. ▼: hours to date "
                f"(as at {as_at:%d/%m/%Y})."
            )

        order = {s: i for i, s in enumerate([rules.STATUS_OVER, rules.STATUS_UNDER, rules.STATUS_ON,
                                             rules.STATUS_CASUAL])}
        table = shown.assign(_o=shown["Status"].map(order)).sort_values(["_o", "Staff"])
        hours = lambda label, help_: st.column_config.NumberColumn(label, format="%.0f", help=help_)  # noqa: E731
        st.dataframe(
            table[["Status", "Staff", "Role", "FTE", "Target", "Teaching", "Duties", "Total", "Variance",
                   "To date", "Left", "Avg hrs/wk", *cfg.SESSIONS, "Disciplines", "Adjustments",
                   "Supervisor"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "Target": hours("Target (h)", f"Role DI hrs/wk × FTE × {cfg.ANNUAL_WEEKS:g} weeks."),
                "Teaching": hours("Teaching (h)", "DI hrs/wk × the teaching weeks of each block, every "
                                  "discipline and session added up."),
                "Duties": hours(f"{rules.DUTIES} (h)", "Higher duties (the DI hours an acting role "
                                "doesn't teach) plus other duties, for the weeks they cover."),
                "Total": hours("Total (h)", "Projected year: teaching + HDA / other duties."),
                "Variance": hours("± Target (h)", "Total − target. Positive = over."),
                "To date": hours("To date (h)", "Teaching + duties in the teaching weeks up to the "
                                 "'As at' date."),
                "Left": hours("Left (h)", "Target − to date: hours still to reach the target by year end."),
                "Avg hrs/wk": st.column_config.NumberColumn(
                    "Avg hrs/wk", format="%.1f",
                    help=f"Total ÷ the {cfg.ANNUAL_WEEKS if not cal_weeks else cal_weeks:g} teaching "
                    "weeks in the Calendar.",
                ),
                **{s: hours(f"{s} (h)", f"Teaching + duties in {yy} {s}.") for s in cfg.SESSIONS},
                "Disciplines": st.column_config.TextColumn(width="medium"),
                "Adjustments": st.column_config.TextColumn("HDA / other duties", width="medium"),
            },
        )
        st.caption(
            f"{rules.STATUS_ON} — projected year within ±{cfg.ON_TRACK_TOLERANCE:.0%} of the target. "
            f"{rules.STATUS_OVER} / {rules.STATUS_UNDER} — outside it. "
            "One row per person, however many disciplines they teach in."
        )

        # discipline view
        with st.expander("By discipline"):
            rows = []
            y_alloc = alloc_df[alloc_df["Session"].isin(year_sessions) & alloc_df["Staff"].isin(shown["Staff"])]
            for d, g in y_alloc.groupby(y_alloc["Discipline"].replace("", "(none)")):
                r = {"Discipline": d, "Staff": g["Staff"].nunique(),
                     "Classes": sum(rules.num(c) for c in g["Classes"])}
                for s in cfg.SESSIONS:
                    r[f"{s} (h)"] = sum(
                        rules.num(line["DI hrs/wk"]) * b["weeks"]
                        for _, line in g[g["Session"] == f"{yy} {s}"].iterrows()
                        for b in blocks if b["Session"] == f"{yy} {s}" and rules.in_block(line["Block"], b["Block"])
                    )
                r["Year (h)"] = sum(r[f"{s} (h)"] for s in cfg.SESSIONS)
                rows.append(r)
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                st.caption("Teaching hours in each discipline, by session.")
            else:
                st.caption("No teaching this year.")

        st.download_button(
            "⬇ Export this view (CSV)",
            data=table.drop(columns=["by_discipline", "_o"]).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"workload_20{yy}.csv",
            mime="text/csv",
        )

    gaps = rules.calendar_gaps(alloc_df, adj_df, cal_df, yy)
    if gaps:
        st.warning("Teaching or duties in blocks with no teaching weeks in the 📅 Calendar "
                   "(counted as zero): " + ", ".join(gaps))
    if blocks and abs(cal_weeks - cfg.ANNUAL_WEEKS) > 1e-9:
        st.info(f"The 📅 Calendar has {cal_weeks:g} teaching weeks in 20{yy}; targets assume "
                f"{cfg.ANNUAL_WEEKS:g}.")
    missing = rules.orphans(staff_df, alloc_df) + rules.orphans(staff_df, adj_df)
    if missing:
        st.warning("Teaching or duties for people not on the Staff list: "
                   + ", ".join(sorted(set(missing))))
    dupes = staff_df["Staff"][staff_df["Staff"].duplicated() & (staff_df["Staff"] != "")]
    if not dupes.empty:
        st.warning("The same name is on the Staff list twice: " + ", ".join(sorted(set(dupes)))
                   + " — keep one row per person; teaching in other disciplines goes on 📚 Teaching.")


def _year_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows in the selected year, plus half-entered rows with no session yet."""
    return df[df["Session"].isin(year_sessions) | (df["Session"] == "")]


# ---------------------------------------------------------------- teaching
with tab_teach:
    st.caption(
        f"One line per class or subject someone teaches in 20{yy}. Pick the session and block "
        "on each line; block *All* = the same hours every block of that session. Someone "
        "teaching in several disciplines just has several lines — the dashboard adds them up."
    )
    vis = _year_rows(alloc_df)
    vis = vis[vis["Staff"].isin(in_view) | (vis["Staff"] == "")]
    if disc_filter:
        vis = vis[vis["Discipline"].isin(disc_filter) | (vis["Discipline"] == "")]
    vis = vis.assign(_s=vis["Session"].map(rules.session_sort_key)).sort_values(
        ["Staff", "_s", "Block", "Subject"]).drop(columns="_s")
    edit_table(
        ALLOCATIONS, vis,
        column_config={
            "Staff": st.column_config.SelectboxColumn("✏️ Staff", options=staff_names, required=True),
            "Session": st.column_config.SelectboxColumn("✏️ Session", options=year_sessions, required=True,
                                                        width="small"),
            "Block": st.column_config.SelectboxColumn("✏️ Block", options=cfg.BLOCK_OPTIONS, required=True, width="small"),
            "Discipline": st.column_config.SelectboxColumn("✏️ Discipline", options=disciplines),
            "Subject": st.column_config.TextColumn("✏️ Subject / unit"),
            "Classes": st.column_config.NumberColumn("✏️ Classes", min_value=0, step=1, width="small"),
            "DI hrs/wk": st.column_config.NumberColumn(
                "✏️ DI hrs/wk", min_value=0, step=0.5, required=True,
                help="Direct Instruction hours per week for this line (face-to-face, online or hybrid).",
            ),
            "Notes": st.column_config.TextColumn("✏️ Notes", width="medium"),
        },
        order=["Staff", "Session", "Block", "Discipline", "Subject", "Classes", "DI hrs/wk", "Notes"],
        defaults={"Session": new_row_session, "Block": cfg.ALL_BLOCKS,
                  "Discipline": disc_filter[0] if len(disc_filter) == 1 else ""},
        key="ed_alloc",
    )

    with st.expander("⧉ Copy teaching from another year"):
        others = [y for y in years if y != yy]
        src = st.selectbox("From", others, key="copy_src", format_func=lambda y: f"20{y}",
                           index=others.index(f"{int(yy) - 1:02d}") if f"{int(yy) - 1:02d}" in others else 0)
        st.caption(f"Copies every line for the staff in view from 20{src} into the same sessions "
                   f"of 20{yy}. Nothing is saved until you press Save.")
        if st.button(f"Copy 20{src} → 20{yy}"):
            rows = wstore.copy_year(alloc_df, src, yy, staff=in_view)
            _add_rows(ALLOCATIONS, rows)
            st.toast(f"Copied {len(rows)} line(s).")
            st.rerun()


# ---------------------------------------------------------------- adjustments
with tab_adj:
    st.caption(cfg.ADJUSTMENT_HELP)
    vis = _year_rows(adj_df)
    vis = vis[vis["Staff"].isin(in_view) | (vis["Staff"] == "")]
    vis = vis.assign(_s=vis["Session"].map(rules.session_sort_key)).sort_values(
        ["Staff", "_s", "Block"]).drop(columns="_s")
    edit_table(
        ADJUSTMENTS, vis,
        column_config={
            "Staff": st.column_config.SelectboxColumn("✏️ Staff", options=staff_names, required=True),
            "Session": st.column_config.SelectboxColumn("✏️ Session", options=year_sessions, required=True,
                                                        width="small"),
            "Block": st.column_config.SelectboxColumn("✏️ Block", options=cfg.BLOCK_OPTIONS, required=True, width="small"),
            "Weeks": st.column_config.NumberColumn(
                "✏️ Weeks", min_value=0, step=1, width="small",
                help="Blank = the whole block. Otherwise how many weeks of the block it covers, "
                "from the block's start.",
            ),
            "Type": st.column_config.SelectboxColumn("✏️ Type", options=cfg.ADJUSTMENT_TYPES, required=True),
            "Acting role": st.column_config.SelectboxColumn(
                "✏️ Acting role", options=cfg.ACTING_ROLES,
                help="Higher duties: the role they're acting in — the DI hours it doesn't teach "
                "become HDA hours. N/A for anything without an acting role; enter hours/week instead.",
            ),
            "DI relief hrs/wk": st.column_config.NumberColumn(
                "✏️ Hours/wk", min_value=0, step=0.5,
                help="Acting role N/A or anything other than higher duties: hours per week it takes "
                "out of teaching.",
            ),
            "Notes": st.column_config.TextColumn("✏️ Notes", width="medium",
                                                 help="e.g. dates, approval reference."),
        },
        order=["Staff", "Session", "Block", "Weeks", "Type", "Acting role", "DI relief hrs/wk", "Notes"],
        defaults={"Session": new_row_session, "Block": cfg.ALL_BLOCKS, "Acting role": cfg.NOT_ACTING},
        key="ed_adj",
    )
    st.caption(" · ".join(
        f"{a} → {b}: {cfg.ROLES[a] - cfg.ROLES[b]:g} h/wk HDA"
        for a, b in [("Teacher (Ongoing)", "Subject Coordinator"), ("Subject Coordinator", "Program Coordinator"),
                     ("Program Coordinator", "Associate Director")]
    ) + " (full-time; × FTE).")


# ---------------------------------------------------------------- calendar
with tab_cal:
    st.caption(
        f"Each block of 20{yy}: when it starts and how many teaching weeks it has. Hours are "
        "DI hrs/wk × these weeks, and 'to date' counts the weeks up to the As at date. "
        f"The annual target assumes {cfg.ANNUAL_WEEKS:g} teaching weeks."
    )
    c1, c2 = st.columns([1, 3])
    c1.metric("Teaching weeks", f"{cal_weeks:g}", delta=f"{cal_weeks - cfg.ANNUAL_WEEKS:+g} vs target"
              if cal_weeks and cal_weeks != cfg.ANNUAL_WEEKS else None, delta_color="off")
    have = {(s, str(b)) for s, b in zip(cal_df["Session"], cal_df["Block"])}
    todo = [(s, b) for s in year_sessions for b in cfg.BLOCKS if (s, b) not in have]
    if todo and c2.button(f"➕ Add the {len(todo)} missing block(s) of 20{yy}"):
        _add_rows(CALENDAR, [{"ID": wstore.new_id(), "Session": s, "Block": b} for s, b in todo])
        st.rerun()
    vis = _year_rows(cal_df)
    vis = vis.assign(_s=vis["Session"].map(rules.session_sort_key)).sort_values(["_s", "Block"]).drop(columns="_s")
    edit_table(
        CALENDAR, vis,
        column_config={
            "Session": st.column_config.SelectboxColumn("✏️ Session", options=year_sessions, required=True),
            "Block": st.column_config.SelectboxColumn("✏️ Block", options=cfg.BLOCKS, required=True, width="small"),
            "Start date": st.column_config.DateColumn("✏️ Start date", format="DD/MM/YYYY"),
            "Teaching weeks": st.column_config.NumberColumn("✏️ Teaching weeks", min_value=0, step=1),
            "Notes": st.column_config.TextColumn("✏️ Notes", width="medium"),
        },
        order=["Session", "Block", "Start date", "Teaching weeks", "Notes"],
        defaults={"Session": new_row_session},
        key="ed_cal",
    )


# ---------------------------------------------------------------- staff
with tab_staff:
    st.caption(
        "Everyone whose workload is managed here — one row per person, even if they teach "
        "in several disciplines. Role sets the annual target (DI hrs/wk × "
        f"{cfg.ANNUAL_WEEKS:g} weeks); FTE scales it. Untick Active for someone who's left — "
        "their history stays."
    )
    vis = staff_df
    if sup_filter:
        vis = vis[vis["Supervisor"].isin(sup_filter) | (vis["Supervisor"] == "")]
    edit_table(
        STAFF, vis.sort_values("Staff"),
        column_config={
            "Staff": st.column_config.TextColumn("✏️ Name", required=True),
            "Role": st.column_config.SelectboxColumn(
                "✏️ Role", options=cfg.STAFF_ROLES, required=True,
                help="Sets the DI hrs/wk behind the annual target — " + _limits + " full-time. "
                "Casual: no target.",
            ),
            "FTE": st.column_config.NumberColumn("✏️ FTE", min_value=0.1, max_value=1.0, step=0.1, width="small"),
            "Supervisor": st.column_config.TextColumn("✏️ Supervisor"),
            "Home discipline": st.column_config.SelectboxColumn("✏️ Home discipline", options=disciplines),
            "Active": st.column_config.CheckboxColumn("✏️ Active", width="small"),
            "Notes": st.column_config.TextColumn("✏️ Notes", width="medium"),
        },
        order=["Staff", "Role", "FTE", "Supervisor", "Home discipline", "Active", "Notes"],
        defaults={"Role": cfg.DEFAULT_ROLE, "FTE": "1", "Active": "TRUE",
                  "Supervisor": sup_filter[0] if len(sup_filter) == 1 else ""},
        key="ed_staff",
    )


# ---------------------------------------------------------------- history
with tab_hist:
    st.caption("Every saved change, newest first. Removed rows keep their last contents here.")
    log = wstore.load_log(_backends()[wstore.LOG_NAME])
    if log.empty:
        st.caption("Nothing saved yet.")
    else:
        h1, h2 = st.columns(2)
        who = h1.selectbox("Staff member", ["Everyone"] + staff_names, key="hist_who")
        what = h2.multiselect("Table", list(wstore.TABLES), format_func=lambda t: t.removeprefix("wl_").title())
        if who != "Everyone":
            log = log[log["Row"].str.split(" · ").str[0] == who]
        if what:
            log = log[log["Table"].isin(what)]
        log = log.assign(Table=log["Table"].str.removeprefix("wl_").str.title())
        st.dataframe(log.drop(columns="ID"), hide_index=True, use_container_width=True)
