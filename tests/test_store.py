"""Tests for store.py seed / load / save / merge logic against an in-memory
fake Backend — no network, no Google."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import loader
import store

FIXTURE = Path(__file__).parent / "fixtures" / "messy_export.csv"


class FakeBackend:
    def __init__(self):
        self.header: list[str] = []
        self.rows: list[list[str]] = []

    def read_records(self) -> list[dict]:
        return [dict(zip(self.header, r)) for r in self.rows]

    def write_all(self, header, rows) -> None:
        self.header = list(header)
        self.rows = [list(map(str, r)) for r in rows]


@pytest.fixture
def cleaned() -> pd.DataFrame:
    return loader.read_export(str(FIXTURE)).df


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend()


# --------------------------------------------------------------------------


def test_seed_writes_every_row_with_blank_review_columns(backend, cleaned):
    stored = store.seed(backend, cleaned)
    assert len(stored) == len(cleaned)
    assert list(stored.columns) == store.STORED_COLUMNS
    assert (stored["Confirmed_R2"] == "FALSE").all()
    for col in ["AssureBand", "InspireBand", "Action", "Effort", "Rationale"]:
        assert (stored[col] == "").all()
    assert set(stored["Confirmed_R1"]) <= {"TRUE", "FALSE"}


def test_load_round_trips_seed(backend, cleaned):
    store.seed(backend, cleaned)
    loaded = store.load(backend)
    assert len(loaded) == len(cleaned)
    assert set(store.STORED_COLUMNS).issubset(loaded.columns)
    assert {"AssessmentNumber_n", "InspireScore_n", "SubjectMaxNumber"} <= set(loaded.columns)


def test_load_empty_sheet_returns_typed_empty_frame(backend):
    loaded = store.load(backend)
    assert loaded.empty
    assert set(store.STORED_COLUMNS).issubset(loaded.columns)


def test_save_applies_changed_row_and_stamps_audit(backend, cleaned):
    store.seed(backend, cleaned)
    loaded = store.load(backend)

    key = loaded.iloc[0]["RowKey"]
    edited = loaded.copy()
    edited.loc[edited["RowKey"] == key, "AssureBand"] = "Assured"
    edited.loc[edited["RowKey"] == key, "Confirmed_R2"] = "TRUE"

    after = store.save(backend, edited, changed_keys=[key], reviewer="Josiah")
    row = after[after["RowKey"] == key].iloc[0]
    assert row["AssureBand"] == "Assured"
    assert row["Confirmed_R2"] == "TRUE"
    assert row["last_saved_by"] == "Josiah"
    assert row["last_saved_at"] != ""
    # an untouched row stays blank
    other = after[after["RowKey"] != key].iloc[0]
    assert other["AssureBand"] == ""
    assert other["last_saved_by"] == ""


def test_save_does_not_clobber_a_concurrent_edit_to_another_row(backend, cleaned):
    store.seed(backend, cleaned)
    loaded = store.load(backend)
    k0, k1 = loaded.iloc[0]["RowKey"], loaded.iloc[1]["RowKey"]

    # someone else saves k1 in the meantime
    concurrent = loaded.copy()
    concurrent.loc[concurrent["RowKey"] == k1, "Rationale"] = "set by Chris"
    store.save(backend, concurrent, changed_keys=[k1], reviewer="Chris")

    # our session only edited k0, from the stale frame
    ours = loaded.copy()
    ours.loc[ours["RowKey"] == k0, "Rationale"] = "set by Josiah"
    after = store.save(backend, ours, changed_keys=[k0], reviewer="Josiah")

    assert after[after["RowKey"] == k0].iloc[0]["Rationale"] == "set by Josiah"
    assert after[after["RowKey"] == k1].iloc[0]["Rationale"] == "set by Chris"


# --------------------------------------------------------------------------
# merge_reupload
# --------------------------------------------------------------------------


def test_merge_reupload_adds_new_and_refreshes_base_but_not_review(backend, cleaned):
    # seed with all but the last row, and confirm/annotate a surviving row
    store.seed(backend, cleaned.iloc[:-1])
    loaded = store.load(backend)
    keep_key = loaded.iloc[0]["RowKey"]
    edited = loaded.copy()
    edited.loc[edited["RowKey"] == keep_key, "AssureBand"] = "Assured"
    edited.loc[edited["RowKey"] == keep_key, "Confirmed_R2"] = "TRUE"
    edited.loc[edited["RowKey"] == keep_key, "QuickWins"] = "tighten the rubric"
    store.save(backend, edited, changed_keys=[keep_key], reviewer="Josiah")

    # re-upload: full set, and a changed score on the kept row
    reup = cleaned.copy()
    reup.loc[reup["RowKey"] == keep_key, "Assure Score"] = "9"

    merged, summary = store.merge_reupload(backend, reup)

    assert len(summary["added"]) == 1                       # the row we withheld
    assert len(merged) == len(cleaned)

    kept = merged[merged["RowKey"] == keep_key].iloc[0]
    assert kept["Assure Score"] == "9"                      # base refreshed
    assert kept["AssureBand"] == "Assured"                  # review untouched
    assert kept["Confirmed_R2"] == "TRUE"                   # confirmation untouched
    assert kept["QuickWins"] == "tighten the rubric"        # note untouched
    assert any(k == keep_key for k, _ in summary["refreshed"])


def test_merge_reupload_reports_rows_missing_from_new_export(backend, cleaned):
    store.seed(backend, cleaned)
    reup = cleaned.iloc[:-2]                                # drop two tasks
    merged, summary = store.merge_reupload(backend, reup)
    assert len(summary["in_sheet_not_in_reupload"]) == 2
    assert len(merged) == len(cleaned)                      # not deleted, just flagged
