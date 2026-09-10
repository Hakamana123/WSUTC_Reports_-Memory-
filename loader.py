"""Read and clean the assessment-mapping export.

Pandas only — no Streamlit, no network, no derivation logic. Turns the raw
CSV into a tidy DataFrame the rest of the tool can rely on:

  * whitespace trimmed everywhere (codes in the real export have stray spaces)
  * fully blank / junk rows dropped
  * `Confirmed` -> `Confirmed_R1` (bool), kept as round-1 history
  * `Quadrant` -> `Quadrant_R1`, normalised; the retired single-label scheme,
    kept only as a reference column beside the derived quadrant
  * numeric helpers: `AssessmentNumber_n` (nullable Int64), `InspireScore_n`,
    `AssureScore_n` (float, NaN where absent), and `SubjectMaxNumber` per
    source file
  * `RowKey` = "<Source File> :: <Program Code> :: <Assessment Number>" —
    stable, and unique even where the same subject is mapped twice in the
    export (a single-program row and an all-programs row share subject code,
    source file and assessment number; only Program Code separates them)

Anything surprising is collected in `LoadResult.warnings` rather than raised,
so a messy export still loads and the reviewer sees what was odd.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd

# The columns the export is expected to have, in order.
INPUT_COLUMNS: list[str] = [
    "Subject Code",
    "Subject Title",
    "Program Code",
    "Assessment Number",
    "Assessment Type",
    "Learning Outcomes",
    "Weighting",
    "Conditions",
    "Inspire Score",
    "Assure Score",
    "Quadrant",
    "Confirmed",
    "Notes/Comments",
    "Source File",
]

# Retired round-1 quadrant labels -> canonical form. Case/space-insensitive.
_QUADRANT_R1_CANON: dict[str, str] = {
    "inspire & assure": "Inspire & Assure",
    "inspire and assure": "Inspire & Assure",
    "inspire": "Inspire",
    "assure": "Assure",
    "low value": "Low value",
    "low quality": "Low value",
    "": "",
}

_TRUE_STRINGS = {"true", "1", "yes", "y", "t"}


@dataclass
class LoadResult:
    df: pd.DataFrame
    dropped_blank_rows: int = 0
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def read_export(source: str | io.IOBase | bytes) -> LoadResult:
    """Read the export from a path, file-like object, or raw bytes."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    raw = pd.read_csv(
        source,
        dtype=str,
        keep_default_na=False,   # empty cell stays "" , not NaN
        skip_blank_lines=False,
    )
    return clean(raw)


def clean(raw: pd.DataFrame) -> LoadResult:
    """Clean an already-read raw frame."""
    warnings: list[str] = []

    missing = [c for c in INPUT_COLUMNS if c not in raw.columns]
    extra = [c for c in raw.columns if c not in INPUT_COLUMNS]
    if missing:
        warnings.append(f"export is missing expected column(s): {missing}")
    if extra:
        warnings.append(f"export has unexpected column(s), kept as-is: {extra}")

    df = raw.copy()
    for col in INPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    # 1. trim whitespace on every string cell; normalise newlines
    str_cols = df.columns
    for col in str_cols:
        df[col] = (
            df[col]
            .fillna("")
            .astype(str)
            .str.replace("\r\n", "\n", regex=False)
            .str.replace("\r", "\n", regex=False)
            .str.strip()
        )

    # 2. drop blank / junk rows (no subject code)
    before = len(df)
    df = df[df["Subject Code"] != ""].copy()
    dropped = before - len(df)

    # 3. round-1 confirmed -> bool history column
    df["Confirmed_R1"] = df["Confirmed"].str.lower().isin(_TRUE_STRINGS)
    df = df.drop(columns=["Confirmed"])

    # 4. round-1 quadrant -> normalised reference column
    canon = [_canon_quadrant_r1(q) for q in df["Quadrant"]]
    unknown = sorted({q for q, c in zip(df["Quadrant"], canon) if c is None})
    if unknown:
        warnings.append(f"unrecognised round-1 Quadrant value(s), kept raw: {unknown}")
    df["Quadrant_R1"] = [q if c is None else c for q, c in zip(df["Quadrant"], canon)]
    df = df.drop(columns=["Quadrant"])

    # 5. numeric helpers
    df["AssessmentNumber_n"] = pd.to_numeric(
        df["Assessment Number"], errors="coerce"
    ).astype("Int64")
    df["InspireScore_n"] = pd.to_numeric(df["Inspire Score"], errors="coerce")
    df["AssureScore_n"] = pd.to_numeric(df["Assure Score"], errors="coerce")

    bad_num = df.loc[
        (df["Assessment Number"] != "") & df["AssessmentNumber_n"].isna(),
        "Assessment Number",
    ].tolist()
    if bad_num:
        warnings.append(
            f"non-numeric Assessment Number(s), treated as missing: {bad_num}"
        )

    n_missing_scores = int(
        (df["InspireScore_n"].isna() | df["AssureScore_n"].isna()).sum()
    )
    if n_missing_scores:
        warnings.append(
            f"{n_missing_scores} row(s) missing an Inspire/Assure score — "
            f"these will need a band set by hand"
        )

    # 6. max assessment number for each mapped subject instance
    #    (Source File + Program Code — the two mapped versions of one subject
    #    are sequenced independently)
    maxn = (
        df.groupby(["Source File", "Program Code"])["AssessmentNumber_n"]
        .max()
        .rename("SubjectMaxNumber")
    )
    df = df.merge(maxn, on=["Source File", "Program Code"], how="left")

    # 7. stable row key
    df["RowKey"] = [
        row_key(sf, pc, an)
        for sf, pc, an in zip(
            df["Source File"], df["Program Code"], df["Assessment Number"]
        )
    ]
    dupes = df["RowKey"][df["RowKey"].duplicated(keep=False)].unique().tolist()
    if dupes:
        warnings.append(f"duplicate RowKey(s) — rows will collide on save: {dupes}")

    df = df.reset_index(drop=True)
    return LoadResult(df=df, dropped_blank_rows=dropped, warnings=warnings)


def row_key(
    source_file: str,
    program_code: str,
    assessment_number: str | int | None,
) -> str:
    """Stable identifier for a task across re-imports."""
    sf = str(source_file).strip()
    pc = str(program_code).strip()
    an = "" if assessment_number is None else str(assessment_number).strip()
    return f"{sf} :: {pc} :: {an}"


def to_export_csv(df: pd.DataFrame, columns: list[str] | None = None) -> str:
    """Serialise the current working frame to CSV text for re-import."""
    out = df[columns] if columns else df
    return out.to_csv(index=False)


# --------------------------------------------------------------------------
# internal
# --------------------------------------------------------------------------


def _canon_quadrant_r1(value: str) -> str | None:
    """Canonical round-1 quadrant label, or None if unrecognised."""
    return _QUADRANT_R1_CANON.get(str(value).strip().lower())
