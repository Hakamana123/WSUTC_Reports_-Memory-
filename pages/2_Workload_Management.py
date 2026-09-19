"""Workload Management — teaching load in hours, for supervisors.

Supervisors keep three lists: the staff they manage, the teaching each person
has in a session (one line per class, with its discipline), and anything that
changes a person's limit — higher duties or relief. The dashboard adds it all
up per person across every discipline they teach in, against the Direct
Instruction limit for their role in The College EA 2022 (Sch B 2.7).

Everything saves to the shared Google Sheet; every change is also appended to
a log tab, shown under History.
"""

from __future__ import annotations

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

from workload_store import ADJUSTMENTS, ALLOCATIONS, STAFF  # noqa: E402

st.set_page_config(page_title="Workload Management", page_icon="📋", layout="wide")
auth.require_access()
st.title("📋 Workload Management")
_limits = " · ".join(
    f"{r} {v:g}"
    for r, v in cfg.ROLES.items() if v is not None
)
st.caption(
    "Teaching load in Direct Instruction (DI) hours per week, against the limits in "
    f"The College Enterprise Agreement 2022 and College practice: {_limits} — pro rata by FTE. "
    "Casual teachers have no limit."
)

NUMERIC = {"FTE", "Classes", "DI hrs/wk", "DI relief hrs/wk"}
BOOL = {"Active"}


# --------------------------------------------------------------------------
# connection + session state
# --------------------------------------------------------------------------


@st.cache_resource(show_spinner=False)
def _backends():
    return wstore.backends_from_secrets(st.secrets)


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

if "wl_data" not in st.session_state:
    with st.spinner("Loading from the Sheet…"):
        _reload()

data: dict[str, pd.DataFrame] = st.session_state["wl_data"]
pending: dict[str, dict[str, set]] = st.session_state["wl_pending"]
staff_df, alloc_df, adj_df = data[STAFF.name], data[ALLOCATIONS.name], data[ADJUSTMENTS.name]


def _fmt(v) -> str:
    """A cell as the string the Sheet stores. Handles numpy scalars too — the
    editor hands back np.bool_ / np.int64 in some rows and Python types in
    others, and both must format identically or every row looks edited."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "TRUE" if v else "FALSE"
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
sessions = sorted(
    {s for s in alloc_df["Session"] if s}
    | {rules.session_of(y, s) for y in (this_year - 1, this_year, this_year + 1) for s in cfg.SESSIONS},
    key=rules.session_sort_key,
)
default = rules.default_session()

st.sidebar.subheader("View")
session = st.sidebar.selectbox("Session", sessions, index=sessions.index(default) if default in sessions else 0)
supervisors = sorted({s for s in staff_df["Supervisor"] if s})
sup_filter = st.sidebar.multiselect("Supervisor", supervisors, help="Show the staff you supervise.")
disciplines = sorted(set(cfg.DISCIPLINES) | {d for d in alloc_df["Discipline"] if d}
                     | {d for d in staff_df["Home discipline"] if d})
disc_filter = st.sidebar.multiselect(
    "Discipline", disciplines,
    help="Show anyone teaching in these disciplines this session — with their "
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
    in_view &= set(alloc_df.loc[(alloc_df["Session"] == session)
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

    # a renamed staff member keeps their teaching and adjustments
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


tab_dash, tab_teach, tab_adj, tab_staff, tab_hist = st.tabs(
    ["📊 Dashboard", "📚 Teaching", "⬆ Higher duties & relief", "👥 Staff", "🗂 History"]
)


# ---------------------------------------------------------------- dashboard
with tab_dash:
    summary = rules.summarise(staff_df, alloc_df, adj_df, session)
    if not summary.empty:
        summary = summary[summary["Staff"].isin(in_view)]

    if staff_df.empty:
        st.info("Start on the 👥 Staff tab — add the people you supervise, then their "
                "teaching on 📚 Teaching.")
    elif summary.empty:
        st.info("Nobody matches the filters in the sidebar.")
    else:
        yy = session.split()[0]
        staff_rec = {r["Staff"]: r for r in staff_df.to_dict("records")}
        yr = [rules.year_average(staff_rec[n], alloc_df, adj_df, yy) for n in summary["Staff"]]
        summary["Year avg"] = [a for a, _ in yr]
        summary["Year limit"] = [l for _, l in yr]

        capped = summary[summary["Status"] != rules.STATUS_CASUAL]
        multi = (summary["by_discipline"].apply(len) > 1).sum()
        m = st.columns(6)
        m[0].metric("Staff", len(summary))
        m[1].metric("⛔ Over", int((summary["Status"] == rules.STATUS_OVER).sum()))
        m[2].metric("⚠ Peak in a block", int((summary["Status"] == rules.STATUS_PEAK).sum()))
        m[3].metric("Spare DI hrs/wk", f"{capped['Spare'].clip(lower=0).sum():.1f}",
                    help="Unallocated DI hours per week across everyone shown, on average over the session.")
        m[4].metric("Acting (higher duties)", int((summary["Acting"] != "").sum()))
        m[5].metric("Across 2+ disciplines", int(multi))

        # load vs limit, stacked by discipline
        long = [
            {"Staff": r["Staff"], "Discipline": d, "DI hrs/wk": h}
            for _, r in summary.iterrows() for d, h in r["by_discipline"].items()
        ]
        if long:
            staff_order = list(summary.sort_values("Avg load", ascending=False)["Staff"])
            y = alt.Y("Staff:N", sort=staff_order, title=None)
            bars = alt.Chart(pd.DataFrame(long)).mark_bar().encode(
                y=y,
                x=alt.X("sum(DI hrs/wk):Q", title="DI hours / week (session average)"),
                color=alt.Color("Discipline:N", legend=alt.Legend(orient="bottom")),
                tooltip=["Staff", "Discipline", alt.Tooltip("DI hrs/wk:Q", format=".1f")],
            )
            limits = alt.Chart(capped[["Staff", "Limit"]]).mark_tick(
                color="black", thickness=2, size=18,
            ).encode(y=y, x="Limit:Q", tooltip=[alt.Tooltip("Limit:Q", title="Limit", format=".1f")])
            chart = alt.layer(bars, limits).properties(height=alt.Step(28))
            st.altair_chart(chart, use_container_width=True)
            st.caption("Bars: each person's teaching by discipline. Black tick: their limit.")

        order = {rules.STATUS_OVER: 0, rules.STATUS_PEAK: 1, rules.STATUS_FULL: 2,
                 rules.STATUS_SPARE: 3, rules.STATUS_CASUAL: 4}
        table = summary.assign(_o=summary["Status"].map(order)).sort_values(["_o", "Staff"])
        block_cols = [f"B{b}" for b in cfg.BLOCKS]
        st.dataframe(
            table[["Status", "Staff", "Role", "FTE", "Limit", "Avg load", "Used %", "Spare",
                   *block_cols, "Year avg", "Year limit", "Disciplines", "Adjustments", "Supervisor"]],
            hide_index=True,
            use_container_width=True,
            column_config={
                "Limit": st.column_config.NumberColumn(format="%.1f", help="DI hrs/wk for the role × FTE, after higher duties and relief."),
                "Avg load": st.column_config.NumberColumn("Load", format="%.1f", help="DI hrs/wk, averaged over the session's 4 blocks."),
                "Used %": st.column_config.ProgressColumn("Used", min_value=0, max_value=100, format="%.0f%%"),
                "Spare": st.column_config.NumberColumn(format="%.1f"),
                **{c: st.column_config.NumberColumn(f"Block {c[1]}", format="%.1f") for c in block_cols},
                "Year avg": st.column_config.NumberColumn(
                    format="%.1f",
                    help="Average load over this year's sessions with any teaching — DI hours "
                    "may vary between sessions but average out over the year (Sch B 2.9).",
                ),
                "Year limit": st.column_config.NumberColumn(format="%.1f"),
                "Disciplines": st.column_config.TextColumn(width="medium"),
                "Adjustments": st.column_config.TextColumn(width="medium"),
            },
        )
        st.caption(
            "⛔ Over — session average above the limit. ⚠ Peak — over in some block but fine on "
            "average (DI hours can vary and average out, Sch B 2.9). ✅ Full — within "
            f"{cfg.FULL_WITHIN_HOURS:g} h of the limit. 🟦 Spare — room for more."
        )

        # discipline view
        with st.expander("By discipline"):
            s_alloc = alloc_df[(alloc_df["Session"] == session) & alloc_df["Staff"].isin(summary["Staff"])]
            if s_alloc.empty:
                st.caption("No teaching allocated this session.")
            else:
                rows = []
                for d, g in s_alloc.groupby(s_alloc["Discipline"].replace("", "(none)")):
                    r = {"Discipline": d, "Staff": g["Staff"].nunique(),
                         "Classes": sum(rules.num(c) for c in g["Classes"])}
                    for b in cfg.BLOCKS:
                        r[f"Block {b}"] = sum(rules.num(h) for h, lb in zip(g["DI hrs/wk"], g["Block"])
                                              if rules.in_block(lb, b))
                    rows.append(r)
                st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
                st.caption("DI hours per week taught in each discipline, by block.")

        st.download_button(
            "⬇ Export this view (CSV)",
            data=table.drop(columns=["by_discipline", "_o"]).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"workload_{session.replace(' ', '_')}.csv",
            mime="text/csv",
        )

    missing = rules.orphans(staff_df, alloc_df) + rules.orphans(staff_df, adj_df)
    if missing:
        st.warning("Teaching or adjustments for people not on the Staff list: "
                   + ", ".join(sorted(set(missing))))
    dupes = staff_df["Staff"][staff_df["Staff"].duplicated() & (staff_df["Staff"] != "")]
    if not dupes.empty:
        st.warning("The same name is on the Staff list twice: " + ", ".join(sorted(set(dupes))))


# ---------------------------------------------------------------- teaching
with tab_teach:
    st.caption(
        f"One line per class or subject someone teaches in **{session}**. Block *All* = "
        "the same hours every block. A person teaching in several disciplines just has "
        "several lines — the dashboard adds them up."
    )
    vis = alloc_df[(alloc_df["Session"] == session)
                   & (alloc_df["Staff"].isin(in_view) | (alloc_df["Staff"] == ""))]
    if disc_filter:
        vis = vis[vis["Discipline"].isin(disc_filter) | (vis["Discipline"] == "")]
    vis = vis.sort_values(["Staff", "Block", "Subject"])
    edit_table(
        ALLOCATIONS, vis,
        column_config={
            "Staff": st.column_config.SelectboxColumn("✏️ Staff", options=staff_names, required=True),
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
        order=["Staff", "Block", "Discipline", "Subject", "Classes", "DI hrs/wk", "Notes"],
        defaults={"Session": session, "Block": cfg.ALL_BLOCKS,
                  "Discipline": disc_filter[0] if len(disc_filter) == 1 else ""},
        key="ed_alloc",
    )

    with st.expander("⧉ Copy teaching from another session"):
        others = [s for s in sessions if s != session]
        yy, _, name = session.partition(" ")
        last_year = f"{int(yy) - 1:02d} {name}"   # same session last year
        src = st.selectbox("From", others, key="copy_src",
                           index=others.index(last_year) if last_year in others else 0)
        st.caption(f"Copies every line for the staff in view from {src} into {session}. "
                   "Nothing is saved until you press Save.")
        if st.button(f"Copy {src} → {session}"):
            rows = wstore.copy_session(alloc_df, src, session, staff=in_view)
            _add_rows(ALLOCATIONS, rows)
            st.toast(f"Copied {len(rows)} line(s).")
            st.rerun()


# ---------------------------------------------------------------- adjustments
with tab_adj:
    st.caption(cfg.ADJUSTMENT_HELP)
    vis = adj_df[(adj_df["Session"] == session)
                 & (adj_df["Staff"].isin(in_view) | (adj_df["Staff"] == ""))].sort_values(["Staff", "Block"])
    edit_table(
        ADJUSTMENTS, vis,
        column_config={
            "Staff": st.column_config.SelectboxColumn("✏️ Staff", options=staff_names, required=True),
            "Block": st.column_config.SelectboxColumn("✏️ Block", options=cfg.BLOCK_OPTIONS, required=True, width="small"),
            "Type": st.column_config.SelectboxColumn("✏️ Type", options=cfg.ADJUSTMENT_TYPES, required=True),
            "Acting role": st.column_config.SelectboxColumn(
                "✏️ Acting role", options=cfg.ACTING_ROLES,
                help="Higher duties only: the role they're acting in. Its DI limit applies instead.",
            ),
            "DI relief hrs/wk": st.column_config.NumberColumn(
                "✏️ Relief DI hrs/wk", min_value=0, step=0.5,
                help="Anything other than higher duties: DI hours per week this frees up.",
            ),
            "Notes": st.column_config.TextColumn("✏️ Notes", width="medium",
                                                 help="e.g. dates, approval reference."),
        },
        order=["Staff", "Block", "Type", "Acting role", "DI relief hrs/wk", "Notes"],
        defaults={"Session": session, "Block": cfg.ALL_BLOCKS},
        key="ed_adj",
    )


# ---------------------------------------------------------------- staff
with tab_staff:
    st.caption(
        "Everyone whose workload is managed here. Role sets the weekly DI limit; FTE "
        "scales it. Untick Active for someone who's left — their history stays."
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
                help="Sets the weekly DI limit — " + _limits + " full-time. Casual: no limit.",
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
