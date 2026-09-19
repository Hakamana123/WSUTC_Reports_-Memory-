"""Google Sheet as the shared system of record.

The app runs on Streamlit Community Cloud, whose disk is wiped on every
redeploy/sleep, so saved state must live outside the app. One Sheet, shared
with a service account, is free, survives restarts, and is one live copy the
whole team sees. No WSU IT involved. See SETUP_GOOGLE_SHEET.md.

Design:
  * only human-owned values are stored. The suggested action, the axis-only
    tier, the position and the *un-confirmed* working bands are all derived
    live in the app from the sidebar cut points / toggle, so they are never
    written here.
  * a band is written only once a reviewer overrides it or confirms the row;
    `derivation.resolve_band` then keeps a confirmed row's band frozen.
  * save re-reads the sheet, applies changed rows by RowKey, writes back —
    last-write-wins per row, which is fine for a small review team.

The Sheet I/O sits behind `Backend` so the seed/load/save/merge logic can be
tested with an in-memory fake and no network.
"""

from __future__ import annotations

import datetime as _dt
from typing import Protocol

import pandas as pd

import loader

# Columns persisted to the Sheet, in order.
_PASSTHROUGH = [c for c in loader.INPUT_COLUMNS if c not in ("Confirmed", "Quadrant")]

REVIEW_COLUMNS = [
    "AssureBand",       # blank until a reviewer overrides / confirms
    "InspireBand",
    "Quadrant_R2",      # frozen on confirm; derived live otherwise
    "Action",           # the reviewer's chosen tier (defaults to suggested)
    "Effort",           # Low / Medium / High
    "QuickWins",
    "ResourceReq",
    "Rationale",
    "Confirmed_R2",     # "TRUE" / "FALSE"
]
AUDIT_COLUMNS = ["last_saved_by", "last_saved_at"]

STORED_COLUMNS = (
    _PASSTHROUGH + ["Confirmed_R1", "Quadrant_R1", "RowKey"]
    + REVIEW_COLUMNS + AUDIT_COLUMNS
)

# Base columns a re-upload is allowed to refresh on an existing row.
_REFRESHABLE_ON_REUPLOAD = [
    "Subject Title", "Assessment Type", "Learning Outcomes", "Weighting",
    "Conditions", "Inspire Score", "Assure Score", "Notes/Comments",
    "Confirmed_R1", "Quadrant_R1",
]


class Backend(Protocol):
    """Minimal Sheet interface: read every row as a dict, replace all rows."""

    def read_records(self) -> list[dict]: ...
    def write_all(self, header: list[str], rows: list[list[str]]) -> None: ...


# --------------------------------------------------------------------------
# gspread-backed implementation
# --------------------------------------------------------------------------


class GSheetBackend:
    def __init__(
        self,
        service_account_info: dict,
        sheet_id: str,
        worksheet: str,
        n_cols: int | None = None,
    ):
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
        self._gc = gspread.authorize(creds)
        self._sheet_id = sheet_id
        self._worksheet_name = worksheet
        self._n_cols = n_cols or len(STORED_COLUMNS)

    def _ws(self):
        import gspread

        sh = self._gc.open_by_key(self._sheet_id)
        try:
            return sh.worksheet(self._worksheet_name)
        except gspread.WorksheetNotFound:
            return sh.add_worksheet(self._worksheet_name, rows=1, cols=self._n_cols)

    def read_records(self) -> list[dict]:
        return self._ws().get_all_records()

    def write_all(self, header: list[str], rows: list[list[str]]) -> None:
        ws = self._ws()
        ws.clear()
        ws.update([header] + rows, value_input_option="RAW")


def backend_from_secrets(secrets) -> GSheetBackend:
    """Build a GSheetBackend from a Streamlit `st.secrets`-like mapping."""
    return GSheetBackend(
        service_account_info=dict(secrets["gcp_service_account"]),
        sheet_id=secrets["sheet"]["id"],
        worksheet=secrets["sheet"].get("worksheet", "working"),
    )


# --------------------------------------------------------------------------
# seed / load / save / merge — pure logic over a Backend
# --------------------------------------------------------------------------


def seed(backend: Backend, cleaned: pd.DataFrame) -> pd.DataFrame:
    """First run: write every cleaned row with review columns blank and
    Confirmed_R2 = FALSE. Returns the stored frame."""
    df = _blank_review_columns(cleaned.copy())
    _write(backend, df)
    return df[STORED_COLUMNS]


def load(backend: Backend) -> pd.DataFrame:
    """Read the Sheet into a DataFrame with STORED_COLUMNS, plus the numeric
    helpers the app needs (`AssessmentNumber_n`, scores, `SubjectMaxNumber`)."""
    records = backend.read_records()
    df = pd.DataFrame(records)
    if df.empty:
        df = pd.DataFrame(columns=STORED_COLUMNS)
    for col in STORED_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[STORED_COLUMNS].astype(str).replace({"nan": "", "None": ""})
    return _add_helpers(df)


def save(
    backend: Backend,
    edited: pd.DataFrame,
    changed_keys: list[str],
    reviewer: str,
) -> pd.DataFrame:
    """Apply the changed rows onto a fresh read of the Sheet and write back.

    Rows not in `changed_keys` are taken from the current Sheet (so a
    concurrent save by someone else is not clobbered)."""
    current = load(backend).set_index("RowKey", drop=False)
    edited = edited.set_index("RowKey", drop=False)

    stamp = _now_iso()
    changed = set(changed_keys)
    for key in changed:
        if key not in edited.index:
            continue
        row = edited.loc[key, STORED_COLUMNS].copy()
        row["last_saved_by"] = reviewer
        row["last_saved_at"] = stamp
        current.loc[key, STORED_COLUMNS] = row.values

    # rows that exist only in `edited` (brand new) also go in
    for key in edited.index.difference(current.index):
        row = edited.loc[key, STORED_COLUMNS].copy()
        row["last_saved_by"] = reviewer
        row["last_saved_at"] = stamp
        current.loc[key] = row

    out = current.reset_index(drop=True)
    _write(backend, out)
    return _add_helpers(out[STORED_COLUMNS])


def merge_reupload(backend: Backend, new_cleaned: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Re-import a fresh export: add tasks with new RowKeys, refresh the base
    columns on existing rows, and never touch a review column, note, or
    Confirmed_R2. Returns (stored frame, summary)."""
    current = load(backend).set_index("RowKey", drop=False)
    incoming = _blank_review_columns(new_cleaned.copy()).set_index("RowKey", drop=False)

    added, refreshed = [], []
    for key, inc in incoming.iterrows():
        if key not in current.index:
            current.loc[key] = inc[STORED_COLUMNS]
            added.append(key)
        else:
            deltas = [
                c for c in _REFRESHABLE_ON_REUPLOAD
                if str(current.loc[key, c]) != str(inc[c])
            ]
            if deltas:
                for c in deltas:
                    current.loc[key, c] = inc[c]
                refreshed.append((key, deltas))

    removed = [k for k in current.index if k not in incoming.index]

    out = current.reset_index(drop=True)
    _write(backend, out)
    summary = {
        "added": added,
        "refreshed": refreshed,
        "in_sheet_not_in_reupload": removed,
    }
    return _add_helpers(out[STORED_COLUMNS]), summary


# --------------------------------------------------------------------------
# internal
# --------------------------------------------------------------------------


def _blank_review_columns(df: pd.DataFrame) -> pd.DataFrame:
    for col in STORED_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["Confirmed_R2"] = df["Confirmed_R2"].replace("", "FALSE")
    df["Confirmed_R1"] = df["Confirmed_R1"].map(_as_sheet_bool)
    return df[STORED_COLUMNS]


def _write(backend: Backend, df: pd.DataFrame) -> None:
    frame = df.copy()
    for col in STORED_COLUMNS:
        if col not in frame.columns:
            frame[col] = ""
    frame = frame[STORED_COLUMNS].fillna("").astype(str)
    backend.write_all(STORED_COLUMNS, frame.values.tolist())


def _add_helpers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["AssessmentNumber_n"] = pd.to_numeric(
        df["Assessment Number"], errors="coerce"
    ).astype("Int64")
    df["InspireScore_n"] = pd.to_numeric(df["Inspire Score"], errors="coerce")
    df["AssureScore_n"] = pd.to_numeric(df["Assure Score"], errors="coerce")
    maxn = (
        df.groupby(["Source File", "Program Code"])["AssessmentNumber_n"]
        .max()
        .rename("SubjectMaxNumber")
    )
    df = df.merge(maxn, on=["Source File", "Program Code"], how="left")
    return df


def _as_sheet_bool(v) -> str:
    if isinstance(v, str):
        return "TRUE" if v.strip().lower() in {"true", "1", "yes"} else "FALSE"
    return "TRUE" if bool(v) else "FALSE"


def _now_iso() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
