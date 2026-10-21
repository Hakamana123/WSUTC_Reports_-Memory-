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
import workload_export as wexport
import workload_rules as rules
import workload_import as wimport
import workload_store as wstore

# Streamlit Cloud pulls a new commit without restarting Python: this page is
# re-read from disk every run, but helper modules imported before the pull
# (store.py, via IA Mapping) stay as the old code until the app is rebooted.
# Reload them, in dependency order, so a push always takes effect here.
for _m in (store, cfg, rules, wstore, wimport, wexport):
    importlib.reload(_m)

from workload_store import ADJUSTMENTS, ALLOCATIONS, CALENDAR, PLANS, STAFF  # noqa: E402

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

NUMERIC = {"FTE", "Classes", "DI hrs/wk", "DI relief hrs/wk", "Weeks", "Teaching weeks", "Target (h)",
           "Other allocated (h)", "Summer hrs needed"}
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
cal_df, plans_df = data[CALENDAR.name], data[PLANS.name]


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
    | {str(y).strip()[-2:] for y in plans_df["Year"] if str(y).strip()}
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
    "Program", disciplines,
    help="Show anyone teaching in these programs this year — with their "
    "whole load, including hours in other programs.",
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
        for t in (ALLOCATIONS, ADJUSTMENTS, PLANS):
            tdf = data[t.name]
            hit = tdf["Staff"] == old_name
            if hit.any():
                tdf.loc[hit, "Staff"] = new_name
                pending[t.name]["changed"] |= set(tdf.loc[hit, "ID"])
    _bump()
    st.rerun()


staff_names = sorted(n for n in staff_df["Staff"] if n)

# the Teaching and Duties editors' columns — also used by the grid's cell editor
ALLOC_COLUMNS = {
    "Staff": st.column_config.SelectboxColumn("✏️ Staff", options=staff_names, required=True),
    "Session": st.column_config.SelectboxColumn("✏️ Session", options=year_sessions, required=True,
                                                width="small"),
    "Block": st.column_config.SelectboxColumn("✏️ Block", options=cfg.BLOCK_OPTIONS, required=True, width="small"),
    "Discipline": st.column_config.SelectboxColumn("✏️ Program", options=disciplines),
    "Subject": st.column_config.TextColumn("✏️ Subject / unit"),
    "Classes": st.column_config.NumberColumn("✏️ Classes", min_value=0, step=1, width="small"),
    "DI hrs/wk": st.column_config.NumberColumn(
        "✏️ DI hrs/wk", min_value=0, step=0.5, required=True,
        help="Direct Instruction hours per week for this line (face-to-face, online or hybrid).",
    ),
    "Notes": st.column_config.TextColumn("✏️ Notes", width="medium"),
}
ALLOC_ORDER = ["Staff", "Session", "Block", "Discipline", "Subject", "Classes", "DI hrs/wk", "Notes"]
ADJ_COLUMNS = {
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
}
ADJ_ORDER = ["Staff", "Session", "Block", "Weeks", "Type", "Acting role", "DI relief hrs/wk", "Notes"]


# --------------------------------------------------------------------------
# tabs
# --------------------------------------------------------------------------


tab_dash, tab_teach, tab_adj, tab_plan, tab_cal, tab_staff, tab_hist = st.tabs(
    ["📊 Dashboard", "📚 Teaching", "⬆ Higher duties & other duties", "🎯 Year plan", "📅 Calendar",
     "👥 Staff", "🗂 History"]
)

# discipline colours; HDA / other duties and other allocated hours always the same greys
_PALETTE = ["#4c78a8", "#f58518", "#e45756", "#72b7b2", "#54a24b", "#eeca3b", "#b279a2",
            "#ff9da6", "#9d755d"]
_DUTIES_COLOUR = "#9e9e9e"
_OTHER = "Other allocated"
_OTHER_COLOUR = "#c7c7c7"


# ---------------------------------------------------------------- dashboard
with tab_dash:
    summary = rules.summarise_year(staff_df, alloc_df, adj_df, cal_df, yy, as_at, plans_df)
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

        grid, load = rules.year_grid(staff_df, alloc_df, adj_df, cal_df, yy)
        load = {k: v for k, v in load.items() if k[0] in set(summary["Staff"])}
        over = rules.over_limit(load)

        labels = rules.grid_labels()
        in_view_grid = grid[grid["Staff"].isin(summary["Staff"])]
        per_block = [float(pd.to_numeric(in_view_grid[f"{lb} h"], errors="coerce").sum()) for lb in labels]
        over_per_block = [sum(1 for _, lb_ in over if lb_ == lb) for lb in labels]
        summer = summary["Summer hrs needed"].fillna(0)
        confirmed = summer[summary["Likelihood"] == "Confirmed"].sum()
        n = summary["Status"].value_counts()

        st.subheader("Summary", divider="gray")
        r1, r2 = st.columns(4), st.columns(4)
        r1[0].metric("Staff", len(summary), border=True)
        r1[1].metric(rules.STATUS_ON, int(n.get(rules.STATUS_ON, 0)), border=True,
                     help=f"Projected year within ±{cfg.ON_TRACK_TOLERANCE:.0%} of the target.")
        r1[2].metric(rules.STATUS_OVER, int(n.get(rules.STATUS_OVER, 0)), border=True)
        r1[3].metric(rules.STATUS_UNDER, int(n.get(rules.STATUS_UNDER, 0)), border=True)
        r2[0].metric("Hours this year", f"{summary['Total'].sum():,.0f}", border=True,
                     chart_data=per_block, chart_type="area",
                     help="Projected hours across everyone shown. Chart: hours in each block, SU2 → SU1 "
                     "(other allocated hours have no block, so aren't in it).")
        r2[1].metric("Blocks over limit", len(over), border=True, chart_data=over_per_block, chart_type="bar",
                     help="Blocks where someone's hours (teaching + duties) are above their role's limit × FTE "
                     "× the block's weeks — even if their year is on track. Casuals have no limit. "
                     "Chart: how many in each block, SU2 → SU1.")
        r2[2].metric(f"{rules.DUTIES} (h)", f"{summary['Duties'].sum():,.0f}", border=True, height="stretch",
                     help="Higher duties and other duties across everyone shown, for the year.")
        r2[3].metric("Summer hrs needed", f"{summer.sum():,.0f}", border=True, height="stretch",
                     delta=f"{confirmed:,.0f} confirmed" if summer.sum() else None, delta_color="off",
                     help="From the 🎯 Year plan: summer teaching hours needed to make up underloads.")

        status_filter = st.multiselect(
            "Show", rules.STATUSES, placeholder="Everyone — or pick a status",
            help="Filter the work patterns, grid and tables by status.",
        )
        shown = summary[summary["Status"].isin(status_filter)] if status_filter else summary

        # the year grid: one row per person, one column per block in calendar
        # order — the block's total hours, then what they do — tinted by how
        # full the block is; then the year against the target
        now = rules.current_block(cal_df, yy, as_at)
        totals = shown.drop_duplicates("Staff").set_index("Staff")[["Target", "Total", "Variance", "Status"]]
        g = (grid[grid["Staff"].isin(shown["Staff"])].drop_duplicates("Staff").join(totals, on="Staff")
             .sort_values("Staff").reset_index(drop=True))

        # work patterns: a dot per person per block, coloured by how full it is
        st.subheader("Work patterns", divider="gray")
        bands = list(cfg.BAND_COLOURS)
        dots = pd.DataFrame([
            {"Staff": name, "Block": lb, "Band": rules.block_band(load[(name, lb)]),
             "Hours": float(g.at[i, f"{lb} h"]), "What": g.at[i, lb],
             "Of limit": "no limit" if load[(name, lb)] is None else f"{load[(name, lb)]:.0%}"}
            for i, name in g["Staff"].items() for lb in labels if (name, lb) in load
        ], columns=["Staff", "Block", "Band", "Hours", "What", "Of limit"])
        y = alt.Y("Staff:N", sort=list(g["Staff"]), title=None, axis=alt.Axis(labelLimit=220))
        x = alt.X("Block:N", sort=labels, title=None, axis=alt.Axis(orient="top", labelAngle=0, domain=False))
        cells_bg = alt.Chart(pd.DataFrame([{"Staff": s_, "Block": lb} for s_ in g["Staff"] for lb in labels])
                             ).mark_rect(color="#888888", opacity=0.08, stroke="white", strokeWidth=2
                                         ).encode(x=x, y=y)
        layers = [cells_bg]
        if now:
            layers.append(alt.Chart(pd.DataFrame([{"Block": now}])).mark_rect(color="#54a24b", opacity=0.12)
                          .encode(x=x))
        layers.append(alt.Chart(dots).mark_circle(size=260, opacity=1).encode(
            x=x, y=y,
            color=alt.Color("Band:N", title=None,
                            scale=alt.Scale(domain=bands, range=list(cfg.BAND_COLOURS.values())),
                            legend=alt.Legend(orient="bottom")),
            tooltip=["Staff", "Block", alt.Tooltip("Hours:Q", format=",.0f"), "Of limit", "What"],
        ))
        st.altair_chart(alt.layer(*layers).properties(height=alt.Step(30)).configure_view(stroke=None),
                        use_container_width=True)
        st.caption(
            "Each dot is a block someone works in, against their role's limit × FTE × the block's weeks: "
            f"🟢 healthy ({cfg.BLOCK_HEALTHY_FROM:.0%}–100 %) · 🟡 light (under {cfg.BLOCK_HEALTHY_FROM:.0%}) · "
            "🟠 over · ⚪ casual (no limit). An empty block is normal — nobody teaches every block."
            + (f" The shaded column is the current block ({now})." if now else "")
        )

        st.subheader("Year grid", divider="gray")

        def _txt(fmt: str):
            # numbers as text, so blanks show blank rather than "None"
            return lambda v: "" if v is None or pd.isna(v) else format(v, fmt)

        view = g[["Staff", "Role", "Program"]].copy()
        for lb in labels:
            view[lb] = [f"{h:,.0f}h · {w}" if h is not None and not pd.isna(h) else ""
                        for h, w in zip(g[f"{lb} h"], g[lb])]
        view["Target"], view["Total"], view["Variance"] = (
            g["Target"].map(_txt(",.0f")), g["Total"].map(_txt(",.0f")), g["Variance"].map(_txt("+,.0f")))
        view["Status"] = g["Status"]

        def _tint(v: float | None) -> str:
            band = rules.block_band(v)
            r, g_, b = (int(cfg.BAND_COLOURS[band][i:i + 2], 16) for i in (1, 3, 5))
            alpha = {cfg.BAND_OVER: 0.5, cfg.BAND_CASUAL: 0.18}.get(band, 0.3)
            bold = "; font-weight: 600" if band == cfg.BAND_OVER else ""
            return f"background-color: rgba({r}, {g_}, {b}, {alpha}){bold}"

        def _grid_css(df: pd.DataFrame) -> pd.DataFrame:
            css = pd.DataFrame("", index=df.index, columns=df.columns)
            for i, name in df["Staff"].items():
                for lb in labels:
                    if (name, lb) in load:
                        css.loc[i, lb] = _tint(load[(name, lb)])
            return css

        styled = view.style.apply(_grid_css, axis=None)
        starts = {(b["Session"], b["Block"]): b for b in blocks}

        def _block_help(session: str, block: str) -> str:
            b = starts.get((f"{yy} {session}", block))
            when = (f"starts {b['start']:%d/%m/%Y}, {b['weeks']:g} weeks" if b and b["start"] is not None
                    else "no dates in the 📅 Calendar")
            return f"{yy} {session} block {block}: {when}. Total hours, then subjects and duties."

        grid_config = {
            "Staff": st.column_config.TextColumn("Name", pinned=True),
            "Role": st.column_config.TextColumn("Role", pinned=True),
            "Program": st.column_config.TextColumn("Program", pinned=True, help="Home program (👥 Staff)."),
            "Target": st.column_config.TextColumn("Target (h)"),
            "Total": st.column_config.TextColumn("Total (h)", help="Projected year, incl. other allocated hours."),
            "Variance": st.column_config.TextColumn("± Target (h)"),
        }
        for s_, b_, lb in cfg.GRID_BLOCKS:
            grid_config[lb] = st.column_config.TextColumn(f"▶ {lb} · now" if lb == now else lb,
                                                          help=_block_help(s_, b_), width="medium")
        picked = st.dataframe(styled, hide_index=True, use_container_width=True, column_config=grid_config,
                              height=min(38 + 35 * len(view), 640), on_select="rerun", selection_mode="single-cell",
                              key=f"wl_grid_{st.session_state.get('wl_grid_k', 0)}")
        st.caption(
            "Each block: its total hours (teaching + duties), then subjects — tagged with the program when "
            "it isn't the person's own — and duties such as *Acting SC*. Colours as in Work patterns; the limit "
            f"for a full-time Teacher's 4-week block is {cfg.ROLES[cfg.DEFAULT_ROLE] * 4:g} h. "
            + (f"▶ marks the block the As at date falls in ({now}). " if now else "")
            + "Other allocated hours (🎯 Year plan) have no block, so they count only in Total. "
            "**Click a block to edit it; click a name to edit their whole year.**"
        )
        st.download_button(
            "⬇ Export the grid (Excel)",
            data=wexport.grid_xlsx(g, labels, load, now, sheet=f"Workload 20{yy}"),
            file_name=f"workload_grid_20{yy}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # click-to-edit: a grid cell opens that person's lines for the block
        # (or, for their name, the year) in the same editors as the tabs. The
        # pick is kept in session state, as the grid's own selection is lost
        # whenever an edit redraws it.
        cells = picked.selection.cells if picked else []
        if cells:
            row, col = cells[0]
            st.session_state["wl_cell"] = (view.iloc[row]["Staff"], col)
        cell = st.session_state.get("wl_cell")
        by_label = {lb: (s, b) for s, b, lb in cfg.GRID_BLOCKS}
        if cell and cell[0] in set(g["Staff"]) and (cell[1] in by_label or cell[1] == "Staff"):
            who, what = cell
            home = staff_df.loc[staff_df["Staff"] == who, "Home discipline"].iloc[0]
            with st.container(border=True):
                t1, t2 = st.columns([5, 1])
                if what == "Staff":
                    sessions, blk = year_sessions, None
                    t1.markdown(f"**✏️ {who} — 20{yy}**")
                else:
                    s, blk = by_label[what]
                    sessions = [f"{yy} {s}"]
                    t1.markdown(f"**✏️ {who} — {what}** ({yy} {s} block {blk})")
                if t2.button("✕ Close", use_container_width=True):
                    st.session_state.pop("wl_cell", None)
                    st.session_state["wl_grid_k"] = st.session_state.get("wl_grid_k", 0) + 1
                    st.rerun()

                def _mine(df: pd.DataFrame) -> pd.DataFrame:
                    hit = (df["Staff"] == who) & df["Session"].isin(sessions)
                    if blk:
                        hit &= df["Block"].map(lambda b: rules.in_block(b, blk))
                    mine = df[hit]
                    return mine.assign(_s=mine["Session"].map(rules.session_sort_key)).sort_values(
                        ["_s", "Block"]).drop(columns="_s")

                new_defaults = {"Staff": who, "Session": sessions[0] if blk else new_row_session,
                                "Block": blk or cfg.ALL_BLOCKS}
                st.caption("Teaching" + (" — lines for block *All* run every block of the session, so a "
                                         "change there applies to all of them." if blk else ""))
                edit_table(ALLOCATIONS, _mine(alloc_df), ALLOC_COLUMNS, ALLOC_ORDER,
                           {**new_defaults, "Discipline": home}, key=f"ed_cell_alloc_{who}_{what}")
                st.caption("Higher duties & other duties")
                edit_table(ADJUSTMENTS, _mine(adj_df), ADJ_COLUMNS, ADJ_ORDER,
                           {**new_defaults, "Acting role": cfg.NOT_ACTING}, key=f"ed_cell_adj_{who}_{what}")
                st.caption("Changes show in the grid straight away; press 💾 Save changes at the top to keep them.")

        st.subheader("Detail", divider="gray")
        with st.expander("Chart and full table"):
            # the year per person: teaching by discipline, then HDA / other duties
            long = [
                {"Staff": r["Staff"], "Part": d, "Hours": h}
                for _, r in shown.iterrows() for d, h in r["by_discipline"].items()
            ] + [
                {"Staff": r["Staff"], "Part": rules.DUTIES, "Hours": r["Duties"]}
                for _, r in shown.iterrows() if r["Duties"]
            ] + [
                {"Staff": r["Staff"], "Part": _OTHER, "Hours": r["Other"]}
                for _, r in shown.iterrows() if r["Other"]
            ]
            if long:
                parts = sorted({x["Part"] for x in long} - {rules.DUTIES, _OTHER})
                colours = [_PALETTE[i % len(_PALETTE)] for i in range(len(parts))]
                y = alt.Y("Staff:N", sort=list(shown.sort_values("Total", ascending=False)["Staff"]),
                          title=None)
                bars = alt.Chart(pd.DataFrame(long)).mark_bar().encode(
                    y=y,
                    x=alt.X("sum(Hours):Q", title=f"Hours in 20{yy} (projected)"),
                    color=alt.Color("Part:N", title=None,
                                    scale=alt.Scale(domain=parts + [rules.DUTIES, _OTHER],
                                                    range=colours + [_DUTIES_COLOUR, _OTHER_COLOUR]),
                                    legend=alt.Legend(orient="bottom")),
                    order=alt.Order("Part:N"),
                    tooltip=["Staff", alt.Tooltip("Part:N", title="Program / duties"),
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
                    "Bars: each person's projected year — teaching by program, then "
                    f"{rules.DUTIES} in grey and {_OTHER.lower()} hours (🎯 Year plan) in light grey. "
                    "Black tick: annual target. ▼: hours to date "
                    f"(as at {as_at:%d/%m/%Y})."
                )

            order = {s: i for i, s in enumerate([rules.STATUS_OVER, rules.STATUS_UNDER, rules.STATUS_ON,
                                                 rules.STATUS_CASUAL])}
            table = shown.assign(_o=shown["Status"].map(order)).sort_values(["_o", "Staff"])
            hours = lambda label, help_: st.column_config.NumberColumn(label, format="%.0f", help=help_)  # noqa: E731
            st.dataframe(
                table[["Status", "Staff", "Role", "FTE", "Target", "Teaching", "Duties", "Other", "Total",
                       "Variance", "To date", "Left", "Avg hrs/wk", "Plan", "Summer hrs needed", "Likelihood",
                       *cfg.SESSIONS, "Disciplines", "Adjustments", "Supervisor"]],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Target": hours("Target (h)", f"The 🎯 Year plan's target if set, otherwise role DI hrs/wk "
                                    f"× FTE × {cfg.ANNUAL_WEEKS:g} weeks."),
                    "Other": hours("Other allocated (h)", "Hours allocated outside the teaching lines — e.g. "
                                   "imported from the load tracking spreadsheet (🎯 Year plan)."),
                    "Plan": st.column_config.TextColumn("Plan?", width="small",
                                                        help="Articulated plan if underloaded (🎯 Year plan)."),
                    "Summer hrs needed": hours("Summer hrs needed", "From the 🎯 Year plan."),
                    "Teaching": hours("Teaching (h)", "DI hrs/wk × the teaching weeks of each block, every "
                                      "program and session added up."),
                    "Duties": hours(f"{rules.DUTIES} (h)", "Higher duties (the DI hours an acting role "
                                    "doesn't teach) plus other duties, for the weeks they cover."),
                    "Total": hours("Total (h)", "Projected year: teaching + HDA / other duties + other "
                                   "allocated."),
                    "Variance": hours("± Target (h)", "Total − target. Positive = over."),
                    "To date": hours("To date (h)", "Teaching + duties in the teaching weeks up to the "
                                     "'As at' date."),
                    "Left": hours("Left (h)", "Target − to date: hours still to reach the target by year end."),
                    "Avg hrs/wk": st.column_config.NumberColumn(
                        "Avg hrs/wk", format="%.1f",
                        help=f"Total ÷ {cfg.ANNUAL_WEEKS:g} weeks — comparable with the role's "
                        "DI hrs/wk (16 for a full-time Teacher).",
                    ),
                    **{s: hours(f"{s} (h)", f"Teaching + duties in {yy} {s}.") for s in cfg.SESSIONS},
                    "Disciplines": st.column_config.TextColumn("Programs", width="medium"),
                    "Adjustments": st.column_config.TextColumn("HDA / other duties", width="medium"),
                },
            )
            st.caption(
                f"{rules.STATUS_ON} — projected year within ±{cfg.ON_TRACK_TOLERANCE:.0%} of the target. "
                f"{rules.STATUS_OVER} / {rules.STATUS_UNDER} — outside it. "
                "One row per person, however many programs they teach in."
            )

        # discipline view
        with st.expander("By program"):
            rows = []
            y_alloc = alloc_df[alloc_df["Session"].isin(year_sessions) & alloc_df["Staff"].isin(shown["Staff"])]
            for d, g in y_alloc.groupby(y_alloc["Discipline"].replace("", "(none)")):
                r = {"Program": d, "Staff": g["Staff"].nunique(),
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
                st.caption("Teaching hours in each program, by session.")
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
    if blocks and cal_weeks < cfg.ANNUAL_WEEKS - 1e-9:
        st.info(f"The 📅 Calendar has only {cal_weeks:g} teaching weeks in 20{yy} — fewer than the "
                f"{cfg.ANNUAL_WEEKS:g} the target assumes, so some blocks are probably missing.")
    missing = (rules.orphans(staff_df, alloc_df) + rules.orphans(staff_df, adj_df)
               + rules.orphans(staff_df, plans_df))
    if missing:
        st.warning("Teaching or duties for people not on the Staff list: "
                   + ", ".join(sorted(set(missing))))
    dupes = staff_df["Staff"][staff_df["Staff"].duplicated() & (staff_df["Staff"] != "")]
    if not dupes.empty:
        st.warning("The same name is on the Staff list twice: " + ", ".join(sorted(set(dupes)))
                   + " — keep one row per person; teaching in other programs goes on 📚 Teaching.")


def _year_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows in the selected year, plus half-entered rows with no session yet."""
    return df[df["Session"].isin(year_sessions) | (df["Session"] == "")]


# ---------------------------------------------------------------- teaching
with tab_teach:
    st.caption(
        f"One line per class or subject someone teaches in 20{yy}. Pick the session and block "
        "on each line; block *All* = the same hours every block of that session. Someone "
        "teaching in several programs just has several lines — the dashboard adds them up."
    )
    vis = _year_rows(alloc_df)
    vis = vis[vis["Staff"].isin(in_view) | (vis["Staff"] == "")]
    if disc_filter:
        vis = vis[vis["Discipline"].isin(disc_filter) | (vis["Discipline"] == "")]
    vis = vis.assign(_s=vis["Session"].map(rules.session_sort_key)).sort_values(
        ["Staff", "_s", "Block", "Subject"]).drop(columns="_s")
    edit_table(
        ALLOCATIONS, vis,
        column_config=ALLOC_COLUMNS,
        order=ALLOC_ORDER,
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
        column_config=ADJ_COLUMNS,
        order=ADJ_ORDER,
        defaults={"Session": new_row_session, "Block": cfg.ALL_BLOCKS, "Acting role": cfg.NOT_ACTING},
        key="ed_adj",
    )
    st.caption(" · ".join(
        f"{a} → {b}: {cfg.ROLES[a] - cfg.ROLES[b]:g} h/wk HDA"
        for a, b in [("Teacher (Ongoing)", "Subject Coordinator"), ("Subject Coordinator", "Program Coordinator"),
                     ("Program Coordinator", "Associate Director")]
    ) + " (full-time; × FTE).")


# ---------------------------------------------------------------- year plan
def _update_rows(table, updates: dict[str, dict]) -> None:
    df = data[table.name]
    for rid, vals in updates.items():
        for c, v in vals.items():
            df.loc[df["ID"] == rid, c] = v
    pending[table.name]["changed"] |= set(updates)


with tab_plan:
    year = rules.year_label(yy)
    st.caption(
        f"One row per person for {year}, all optional. **Target** replaces role × FTE × "
        f"{cfg.ANNUAL_WEEKS:g} weeks (part-year contracts, leave — 0 counts). **Other allocated** "
        "counts hours not entered as 📚 Teaching lines, e.g. the spreadsheet's allocated hours — "
        "don't enter the same teaching both ways. The rest records how an underload will be made up."
    )

    with st.expander("⬆ Import the L&T load tracking spreadsheet"):
        st.caption(
            f"Reads the main sheet and the underload sheet into **{year}**: adds anyone not yet on "
            "👥 Staff (matched by Employee No, then name — existing people keep their role, FTE and "
            "supervisor), and sets each person's Year plan from it: target = required load, other "
            "allocated = allocated hours, plus plan, summer hours, likelihood, subject and details. "
            "Re-importing a newer version refreshes those fields. Nothing is saved until you press Save."
        )
        up = st.file_uploader("Load tracking spreadsheet (.xlsx)", type=["xlsx"], key="wl_import_file")
        if up is not None:
            parsed = wimport.parse_workbook(up)
            ch = wimport.plan_changes(parsed, staff_df, plans_df, year)
            for w in parsed.warnings:
                st.warning(w)
            i1, i2, i3, i4 = st.columns(4)
            i1.metric("People in the file", len(parsed.people))
            i2.metric("New staff", len(ch.new_staff))
            i3.metric(f"New {year} plans", len(ch.new_plans))
            i4.metric("Updates", len(ch.staff_updates) + len(ch.plan_updates))
            st.dataframe(
                pd.DataFrame([{
                    "Name": p["name"], "Employee No": p["emp"], "Unit": p["unit"], "Required": p["required"],
                    "Allocated": p["allocated"], "Plan": p["plan"], "Summer hrs": p["summer"],
                    "Likelihood": p["likelihood"], "Subject": p["subject"], "Details": p["details"],
                } for p in parsed.people]),
                hide_index=True, use_container_width=True, height=250,
            )
            n_changes = (len(ch.new_staff) + len(ch.new_plans) + len(ch.staff_updates)
                         + len(ch.plan_updates))
            if st.button(f"Apply to {year}", disabled=not n_changes,
                         help="Nothing to change." if not n_changes else None):
                _add_rows(STAFF, ch.new_staff)
                _update_rows(STAFF, ch.staff_updates)
                _add_rows(PLANS, ch.new_plans)
                _update_rows(PLANS, ch.plan_updates)
                _bump()
                st.toast(f"{n_changes} change(s) ready — press Save to keep them.")
                st.rerun()

    vis = plans_df[(plans_df["Year"].astype(str).str.strip() == year) | (plans_df["Year"] == "")]
    vis = vis[vis["Staff"].isin(in_view) | (vis["Staff"] == "")].sort_values("Staff")
    edit_table(
        PLANS, vis,
        column_config={
            "Staff": st.column_config.SelectboxColumn("✏️ Staff", options=staff_names, required=True),
            "Target (h)": st.column_config.NumberColumn(
                "✏️ Target (h)", min_value=0, step=1,
                help=f"Blank = role × FTE × {cfg.ANNUAL_WEEKS:g} weeks. 0 = no load this year (e.g. on leave).",
            ),
            "Other allocated (h)": st.column_config.NumberColumn(
                "✏️ Other allocated (h)", min_value=0, step=1,
                help="Hours allocated that aren't 📚 Teaching lines (e.g. from the spreadsheet).",
            ),
            "Plan": st.column_config.SelectboxColumn("✏️ Plan?", options=cfg.PLAN_OPTIONS, width="small",
                                                     help="Articulated plan if underloaded."),
            "Summer hrs needed": st.column_config.NumberColumn("✏️ Summer hrs needed", min_value=0, step=1),
            "Likelihood": st.column_config.SelectboxColumn("✏️ Likelihood", options=cfg.LIKELIHOOD_OPTIONS),
            "Subject": st.column_config.TextColumn("✏️ Subject", help="e.g. EDUC1010"),
            "Notes": st.column_config.TextColumn("✏️ Notes / details", width="large"),
        },
        order=["Staff", "Target (h)", "Other allocated (h)", "Plan", "Summer hrs needed", "Likelihood",
               "Subject", "Notes"],
        defaults={"Year": year},
        key="ed_plan",
    )


# ---------------------------------------------------------------- calendar
with tab_cal:
    st.caption(
        f"Each block of 20{yy}: when it starts and how many teaching weeks it has. Hours are "
        "DI hrs/wk × these weeks, and 'to date' counts the weeks up to the As at date. "
        f"The target stays {cfg.ANNUAL_WEEKS:g} weeks' worth however many blocks the year has — "
        "nobody teaches every block. Breaks between blocks simply aren't listed."
    )
    c1, c2 = st.columns([1, 3])
    c1.metric("Teaching weeks", f"{cal_weeks:g}")
    new_blocks, fills = rules.calendar_fill(cal_df, yy)
    if (new_blocks or fills) and c2.button(
        f"➕ Add the year's blocks, with the known dates ({len(new_blocks)} new, {len(fills)} to fill in)",
        help="Adds any of the year's blocks not yet listed, and fills blank start dates / weeks "
        "from the dates on file. Nothing is saved until you press Save.",
    ):
        for rid, vals in fills.items():
            for c, v in vals.items():
                cal_df.loc[cal_df["ID"] == rid, c] = v
        pending[CALENDAR.name]["changed"] |= set(fills)
        _add_rows(CALENDAR, [{"ID": wstore.new_id(), **r} for r in new_blocks])
        _bump()
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
        "in several programs. Role sets the annual target (DI hrs/wk × "
        f"{cfg.ANNUAL_WEEKS:g} weeks); FTE scales it; a 🎯 Year plan target overrides it for that "
        "year. Untick Active for someone who's left — "
        "their history stays."
    )
    vis = staff_df
    if sup_filter:
        vis = vis[vis["Supervisor"].isin(sup_filter) | (vis["Supervisor"] == "")]
    edit_table(
        STAFF, vis.sort_values("Staff"),
        column_config={
            "Staff": st.column_config.TextColumn("✏️ Name", required=True),
            "Employee No": st.column_config.TextColumn("✏️ Employee No", width="small",
                                                       help="Used to match people on import."),
            "Role": st.column_config.SelectboxColumn(
                "✏️ Role", options=cfg.STAFF_ROLES, required=True,
                help="Sets the DI hrs/wk behind the annual target — " + _limits + " full-time. "
                "Casual: no target.",
            ),
            "FTE": st.column_config.NumberColumn("✏️ FTE", min_value=0.1, max_value=1.0, step=0.1, width="small"),
            "Supervisor": st.column_config.TextColumn("✏️ Supervisor"),
            "Home discipline": st.column_config.SelectboxColumn("✏️ Home program", options=disciplines),
            "Active": st.column_config.CheckboxColumn("✏️ Active", width="small"),
            "Notes": st.column_config.TextColumn("✏️ Notes", width="medium"),
        },
        order=["Staff", "Employee No", "Role", "FTE", "Supervisor", "Home discipline", "Active", "Notes"],
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
