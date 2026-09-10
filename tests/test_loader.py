"""Tests for loader.py against a fixture that reproduces the real export's mess:
embedded newlines, blank + junk rows, whitespace-padded codes, a subject code
that appears under two source files, missing scores, a missing assessment
number, and inconsistent / unknown round-1 quadrant labels.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import loader

FIXTURE = Path(__file__).parent / "fixtures" / "messy_export.csv"


@pytest.fixture(scope="module")
def result() -> loader.LoadResult:
    return loader.read_export(str(FIXTURE))


@pytest.fixture(scope="module")
def df(result) -> pd.DataFrame:
    return result.df


# --------------------------------------------------------------------------
# row counts / blank rows
# --------------------------------------------------------------------------


def test_blank_and_junk_rows_dropped(result, df):
    # fixture has 10 data rows; 2 are blank/junk (no subject code)
    assert result.dropped_blank_rows == 2
    assert len(df) == 8


def test_embedded_newline_row_stays_one_row(df):
    chem2 = df[(df["Subject Code"] == "CHEM1013") & (df["Assessment Number"] == "2")]
    assert len(chem2) == 1
    assert "\n" in chem2.iloc[0]["Conditions"]
    assert "\n" in chem2.iloc[0]["Notes/Comments"]


# --------------------------------------------------------------------------
# whitespace
# --------------------------------------------------------------------------


def test_whitespace_trimmed_from_codes(df):
    proc = df[df["Subject Code"] == "PROC1009"]
    assert len(proc) == 1
    row = proc.iloc[0]
    assert row["Subject Code"] == "PROC1009"
    assert row["Program Code"] == "7193"
    assert row["Subject Title"] == "Materials Science in Engineering (WSTC)"


# --------------------------------------------------------------------------
# Confirmed -> Confirmed_R1
# --------------------------------------------------------------------------


def test_confirmed_becomes_bool_history_column(df):
    assert "Confirmed" not in df.columns
    assert df["Confirmed_R1"].dtype == bool
    chem1 = df[(df["Subject Code"] == "CHEM1013") & (df["Assessment Number"] == "1")]
    assert bool(chem1.iloc[0]["Confirmed_R1"]) is True
    proc = df[df["Subject Code"] == "PROC1009"].iloc[0]
    assert not proc["Confirmed_R1"]          # "false"


# --------------------------------------------------------------------------
# Quadrant -> Quadrant_R1 (normalised, retired scheme, reference only)
# --------------------------------------------------------------------------


def test_quadrant_r1_normalised(df):
    assert "Quadrant" not in df.columns
    proc = df[df["Subject Code"] == "PROC1009"].iloc[0]
    assert proc["Quadrant_R1"] == "Low value"        # was "Low Value"
    cart = df[df["Program Code"] == "7194"].iloc[0]
    assert cart["Quadrant_R1"] == "Inspire"          # was "inspire"


def test_unknown_quadrant_kept_raw_and_warned(df, result):
    humn = df[df["Subject Code"] == "HUMN1070"].iloc[0]
    assert humn["Quadrant_R1"] == "Weird Label"
    assert any("unrecognised round-1 Quadrant" in w for w in result.warnings)


# --------------------------------------------------------------------------
# numeric helpers
# --------------------------------------------------------------------------


def test_score_helpers(df):
    chem1 = df[(df["Subject Code"] == "CHEM1013") & (df["Assessment Number"] == "1")].iloc[0]
    assert chem1["InspireScore_n"] == 7.0
    assert chem1["AssureScore_n"] == 6.0


def test_missing_score_is_na_and_warned(df, result):
    bios = df[df["Subject Code"] == "BIOS1040"].iloc[0]
    assert pd.isna(bios["AssureScore_n"])
    assert bios["InspireScore_n"] == 8.0
    assert any("missing an Inspire/Assure score" in w for w in result.warnings)


def test_non_numeric_assessment_number_is_na_and_warned(df, result):
    mech = df[df["Subject Code"] == "MECH2004"].iloc[0]
    assert pd.isna(mech["AssessmentNumber_n"])
    assert mech["Assessment Number"] == "Part A"          # raw value preserved
    assert mech["RowKey"].endswith(":: Part A")
    assert any("non-numeric Assessment Number" in w for w in result.warnings)


# --------------------------------------------------------------------------
# SubjectMaxNumber
# --------------------------------------------------------------------------


def test_subject_max_number_per_mapped_instance(df):
    chem = df[df["Subject Code"] == "CHEM1013"]
    assert set(chem["SubjectMaxNumber"]) == {2}
    cart = df[df["Subject Code"] == "CART1009"]
    assert set(cart["SubjectMaxNumber"]) == {1}


# --------------------------------------------------------------------------
# RowKey
# --------------------------------------------------------------------------


def test_row_key_format():
    assert loader.row_key("Foo - 2026.03", "7194", "2") == "Foo - 2026.03 :: 7194 :: 2"
    assert loader.row_key("Foo ", " 7194 ", " 2 ") == "Foo :: 7194 :: 2"
    assert loader.row_key("Foo", "7194", None) == "Foo :: 7194 :: "


def test_same_subject_mapped_twice_gets_distinct_keys(df):
    # same subject code, source file and assessment number; only Program Code differs
    cart = df[df["Subject Code"] == "CART1009"]
    assert len(cart) == 2
    assert cart["Source File"].nunique() == 1
    assert cart["Assessment Number"].tolist() == ["1", "1"]
    assert cart["RowKey"].nunique() == 2


def test_no_duplicate_row_keys_in_fixture(df, result):
    assert df["RowKey"].is_unique
    assert not any("duplicate RowKey" in w for w in result.warnings)


# --------------------------------------------------------------------------
# round trip
# --------------------------------------------------------------------------


def test_to_export_csv_round_trips(df):
    csv_text = loader.to_export_csv(df)
    reloaded = pd.read_csv(pd.io.common.StringIO(csv_text), dtype=str, keep_default_na=False)
    assert len(reloaded) == len(df)
    assert "RowKey" in reloaded.columns


def test_bytes_input_works():
    res = loader.read_export(FIXTURE.read_bytes())
    assert len(res.df) == 8
