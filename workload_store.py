"""Workload Management's memory: five tabs in its own Google Sheet.

  * `wl_staff`        — who's on the team: role, FTE, supervisor.
  * `wl_allocations`  — teaching: one line per class/subject a person teaches in
                        a session (and block), with its discipline and DI hours.
  * `wl_adjustments`  — higher duties and other duties that take hours out of
                        a person's teaching for a session/block (or part of one).
  * `wl_calendar`     — each block's start date and number of teaching weeks.
  * `wl_log`          — append-only history across all three: who changed
                        which field, from what, to what, when — and the full
                        contents of anything removed. Never edited.

Loads, limits and statuses are never stored; `workload_rules` derives them
live. Same `Backend` protocol as `store.py`, so it's tested against the same
in-memory fake.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import dataclass

import pandas as pd

from store import Backend, GSheetBackend


@dataclass(frozen=True)
class Table:
    name: str             # also the default worksheet name
    columns: list[str]    # input columns, excluding ID and audit
    label_cols: tuple     # what identifies a row to a human in the log

    @property
    def all_columns(self) -> list[str]:
        return ["ID"] + self.columns + AUDIT_COLUMNS


AUDIT_COLUMNS = ["last_saved_by", "last_saved_at"]

STAFF = Table(
    "wl_staff",
    ["Staff", "Role", "FTE", "Supervisor", "Home discipline", "Active", "Notes"],
    ("Staff",),
)
ALLOCATIONS = Table(
    "wl_allocations",
    ["Staff", "Session", "Block", "Discipline", "Subject", "Classes", "DI hrs/wk", "Notes"],
    ("Staff", "Session", "Subject"),
)
ADJUSTMENTS = Table(
    "wl_adjustments",
    ["Staff", "Session", "Block", "Weeks", "Type", "Acting role", "DI relief hrs/wk", "Notes"],
    ("Staff", "Session", "Type"),
)
CALENDAR = Table(
    "wl_calendar",
    ["Session", "Block", "Start date", "Teaching weeks", "Notes"],
    ("Session", "Block"),
)
TABLES = {t.name: t for t in (STAFF, ALLOCATIONS, ADJUSTMENTS, CALENDAR)}

LOG_NAME = "wl_log"
LOG_COLUMNS = ["At", "By", "Table", "ID", "Row", "Change", "Field", "From", "To"]


# The Workload Management Sheet. Not a secret: it's useless without the
# service account, which must be shared on it as an Editor. `[workload]
# sheet_id` in secrets overrides it.
DEFAULT_SHEET_ID = "1A9kECrfTxCQod5EC2s0O-WRIg-ywnB8Ry72t3AbIctU"


def backends_from_secrets(secrets) -> dict[str, GSheetBackend]:
    """{table name: backend} for every table plus the log."""
    sa = dict(secrets["gcp_service_account"])
    sheet_id = secrets.get("workload", {}).get("sheet_id") or DEFAULT_SHEET_ID
    out = {t.name: GSheetBackend(sa, sheet_id, t.name, len(t.all_columns)) for t in TABLES.values()}
    out[LOG_NAME] = GSheetBackend(sa, sheet_id, LOG_NAME, len(LOG_COLUMNS))
    return out


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def empty(table: Table) -> pd.DataFrame:
    return pd.DataFrame(columns=table.all_columns)


def load(backend: Backend, table: Table) -> pd.DataFrame:
    df = pd.DataFrame(backend.read_records())
    if df.empty:
        return empty(table)
    df = df.reindex(columns=table.all_columns, fill_value="")
    return df.astype(str).replace({"nan": "", "None": ""})


def load_log(log_backend: Backend) -> pd.DataFrame:
    df = pd.DataFrame(log_backend.read_records())
    if df.empty:
        return pd.DataFrame(columns=LOG_COLUMNS)
    df = df.reindex(columns=LOG_COLUMNS, fill_value="").astype(str)
    return df.iloc[::-1].reset_index(drop=True)   # newest first


def row_label(table: Table, row) -> str:
    return " · ".join(str(row[c]) for c in table.label_cols if str(row[c]))


def save(
    backend: Backend,
    log_backend: Backend,
    table: Table,
    edited: pd.DataFrame,
    changed_ids,
    removed_ids,
    by: str,
) -> pd.DataFrame:
    """Apply changed / new / removed rows onto a fresh read of the tab, write
    back, and log one line per field that actually changed.

    Rows not named are taken from the current tab, so a concurrent save by
    another supervisor to other rows isn't clobbered."""
    cols = table.all_columns
    current = load(backend, table).set_index("ID", drop=False)
    edited = edited.reindex(columns=cols, fill_value="").set_index("ID", drop=False)
    stamp = _now()
    log: list[list[str]] = []
    removed_ids = set(removed_ids)

    for key in changed_ids:
        if key in removed_ids or key not in edited.index:
            continue
        new = edited.loc[key, cols].fillna("").astype(str).copy()
        new["last_saved_by"] = by
        new["last_saved_at"] = stamp
        label = row_label(table, new)
        if key in current.index:
            old = current.loc[key, cols]
            diffs = [c for c in table.columns if str(old[c]) != str(new[c])]
            if not diffs:
                continue
            log += [[stamp, by, table.name, key, label, "edited", c, str(old[c]), str(new[c])] for c in diffs]
            current.loc[key, cols] = new.values
        else:
            log.append([stamp, by, table.name, key, label, "added", "", "", ""])
            current.loc[key] = new[cols]

    for key in removed_ids:
        if key in current.index:
            old = current.loc[key]
            snapshot = "; ".join(f"{c}={old[c]}" for c in table.columns if str(old[c]))
            log.append([stamp, by, table.name, key, row_label(table, old), "removed", "", snapshot, ""])
            current = current.drop(index=key)

    out = current.reset_index(drop=True)
    backend.write_all(cols, out.reindex(columns=cols, fill_value="").fillna("").astype(str).values.tolist())
    if log:
        existing = log_backend.read_records()
        rows = [[str(r.get(c, "")) for c in LOG_COLUMNS] for r in existing]
        log_backend.write_all(LOG_COLUMNS, rows + log)
    return out[cols]


def copy_session(allocations: pd.DataFrame, source: str, target: str, staff=None) -> list[dict]:
    """New allocation rows for `target`, copied from `source` (optionally only
    for the named staff). Not saved — the caller adds and saves them."""
    src = allocations[allocations["Session"] == source]
    if staff is not None:
        src = src[src["Staff"].isin(staff)]
    rows = []
    for _, r in src.iterrows():
        row = {c: r[c] for c in ALLOCATIONS.columns}
        row.update({"ID": new_id(), "Session": target, "Notes": f"Copied from {source}."})
        rows.append(row)
    return rows


def copy_year(allocations: pd.DataFrame, source_yy: str, target_yy: str, staff=None) -> list[dict]:
    """copy_session for every session of year `source_yy` ("26") into the
    same session of `target_yy`."""
    rows = []
    for s in sorted({s for s in allocations["Session"] if str(s).startswith(f"{source_yy} ")}):
        rows += copy_session(allocations, s, f"{target_yy} {s.partition(' ')[2]}", staff=staff)
    return rows


def _now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
